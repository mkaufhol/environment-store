"""The adapter contract suite: the executable form of `environment_store.core.adapter.Adapter`.

Every adapter test module subclasses `AdapterContract` and implements only `make_backend`:

```python
class TestSqliteContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory: ...
```

`make_backend` must be a `classmethod` fixture with **class scope or broader** (Hypothesis refuses
function-scoped fixtures, because one fixture value would be shared by all examples; pytest
deprecates class-scoped instance-method fixtures) and returns a factory. Each call of the factory
returns a context manager around a fresh, empty, isolated `Backend`; leaving the context cleans
the backend up. The Hypothesis tests create one backend per example, every other test one per
test.

A `Backend` opens any number of independent adapter instances on the same storage, which the
suite uses for persistence and race tests.
"""

import dataclasses
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta, timezone
from typing import Final, Protocol

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode, StoreRecord
from tests.support.strategies import plain_records, sealed_records, store_names

__all__ = ["AdapterContract", "Backend", "BackendFactory"]


class Backend(Protocol):
    """A fresh, empty, isolated storage location for one test or Hypothesis example."""

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> Adapter:
        """Open a new adapter instance on this backend; every call returns a new instance."""
        ...


type BackendFactory = Callable[[], AbstractContextManager[Backend]]
"""Returns a context manager that yields a fresh backend and cleans it up on exit."""

_T0: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_T1: Final[datetime] = datetime(2026, 11, 6, 12, 30, 15, 123456, tzinfo=UTC)
_KEYFILE_META: Final[CipherMeta] = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE)
_PASSPHRASE_META: Final[CipherMeta] = CipherMeta(
    cipher=Cipher.AES256GCM,
    mode=KeyMode.PASSPHRASE,
    kdf=KdfParams(iterations=2, memory_kib=19456, lanes=1, salt=bytes(range(16))),
)
# Path traversal, separators, case, length, control characters and non-ASCII (D27).
_INVALID_NAMES: Final[tuple[str, ...]] = (
    "",
    "..",
    "../x",
    "a/b",
    "a\\b",
    "/abs",
    "A",
    "Base",
    "-a",
    "_a",
    "a.json",
    "a b",
    "a\n",
    "a\x00",
    "x" * 64,
    "café",
)
# Code point order: '-' < digits < '_' < letters. A collating database sorts these differently.
_UNSORTED_NAMES: Final[tuple[str, ...]] = ("b", "a_1", "a-2", "a", "0x", "z9", "a1", "a-")
_RACERS: Final[int] = 8
_RACE_TIMEOUT: Final[float] = 30.0


def _plain(
    name: str = "base",
    *,
    variables: dict[str, str] | None = None,
    revision: int = 1,
    created_at: datetime = _T0,
    updated_at: datetime | None = None,
) -> StoreRecord:
    return StoreRecord.plain(
        name=name,
        variables={"HOST": "localhost"} if variables is None else variables,
        revision=revision,
        created_at=created_at,
        updated_at=updated_at,
    )


def _sealed(
    name: str = "secret",
    *,
    meta: CipherMeta = _KEYFILE_META,
    ciphertext: bytes = b"\x00\x01nonce-and-ciphertext\xff",
    revision: int = 1,
) -> StoreRecord:
    return StoreRecord.sealed(
        name=name, ciphertext=ciphertext, cipher_meta=meta, created_at=_T0, revision=revision
    )


def _next(record: StoreRecord, **variables: str) -> StoreRecord:
    """The record of the next revision, as the service writes it."""
    return _plain(
        record.name,
        variables=variables,
        revision=record.revision + 1,
        created_at=record.created_at,
        updated_at=record.updated_at + timedelta(seconds=1),
    )


def _forge_name(record: StoreRecord, name: str) -> StoreRecord:
    # Bypasses the model's validation, as a buggy or malicious caller could.
    object.__setattr__(record, "name", name)
    return record


def _first_revision_records() -> st.SearchStrategy[StoreRecord]:
    return st.one_of(plain_records(revisions=st.just(1)), sealed_records(revisions=st.just(1)))


def _any_records() -> st.SearchStrategy[StoreRecord]:
    return st.one_of(plain_records(), sealed_records())


def _race[T](backend: Backend, action: Callable[[Adapter], T]) -> list[T | Exception]:
    """Run `action` in parallel threads, each on its own adapter instance, released together.

    Returns:
        Per thread the result or the raised library error.
    """
    barrier = threading.Barrier(_RACERS, timeout=_RACE_TIMEOUT)

    def run() -> T | Exception:
        with backend.open() as adapter:
            barrier.wait()
            try:
                return action(adapter)
            except (StoreExistsError, ConcurrentModificationError) as err:
                return err

    with ThreadPoolExecutor(max_workers=_RACERS) as pool:
        futures = [pool.submit(run) for _ in range(_RACERS)]
        return [future.result(timeout=_RACE_TIMEOUT) for future in futures]


class AdapterContract:
    """Behaviour every adapter must show; subclass it and implement `make_backend`."""

    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls) -> BackendFactory:
        """Return a factory of fresh, empty, isolated backends (class scope or broader)."""
        raise NotImplementedError

    @pytest.fixture
    def backend(self, make_backend: BackendFactory) -> Iterator[Backend]:
        with make_backend() as backend:
            yield backend

    @pytest.fixture
    def adapter(self, backend: Backend) -> Iterator[Adapter]:
        with backend.open() as adapter:
            yield adapter

    # --- listing ---------------------------------------------------------------------------

    def test_new_backend_lists_no_stores(self, adapter: Adapter) -> None:
        assert adapter.list_stores() == []

    def test_listing_is_sorted_by_name_in_code_point_order(self, adapter: Adapter) -> None:
        for name in _UNSORTED_NAMES:
            adapter.create_store(_plain(name))

        assert [info.name for info in adapter.list_stores()] == sorted(_UNSORTED_NAMES)

    def test_listing_reports_encryption_key_mode_revision_and_timestamps(
        self, adapter: Adapter
    ) -> None:
        plain = _plain("plain", updated_at=_T1)
        keyfile = _sealed("keyfile")
        passphrase = _sealed("passphrase", meta=_PASSPHRASE_META)
        for record in (plain, keyfile, passphrase):
            adapter.create_store(record)
        written = _next(plain, A="1")
        adapter.write_store(written, expected_revision=1)

        assert adapter.list_stores() == [keyfile.info, passphrase.info, written.info]
        assert [info.key_mode for info in adapter.list_stores()] == [
            KeyMode.KEYFILE,
            KeyMode.PASSPHRASE,
            None,
        ]

    def test_listing_returns_a_new_list_each_time(self, adapter: Adapter) -> None:
        adapter.create_store(_plain())
        adapter.list_stores().clear()

        assert [info.name for info in adapter.list_stores()] == ["base"]

    @given(names=st.sets(store_names(), max_size=6))
    def test_listing_any_names_is_sorted(
        self, make_backend: BackendFactory, names: set[str]
    ) -> None:
        with make_backend() as backend, backend.open() as adapter:
            for name in names:
                adapter.create_store(_plain(name))

            assert [info.name for info in adapter.list_stores()] == sorted(names)

    # --- create / read ---------------------------------------------------------------------

    @pytest.mark.parametrize(
        "record",
        [
            _plain(),
            _plain(variables={}),
            _sealed(),
            _sealed(meta=_PASSPHRASE_META),
            _sealed(ciphertext=b""),
        ],
        ids=["plain", "plain-empty", "sealed-keyfile", "sealed-passphrase", "sealed-empty"],
    )
    def test_create_then_read_returns_the_same_record(
        self, adapter: Adapter, record: StoreRecord
    ) -> None:
        adapter.create_store(record)

        assert adapter.read_store(record.name) == record

    @given(record=_first_revision_records())
    def test_create_then_read_round_trips_any_record(
        self, make_backend: BackendFactory, record: StoreRecord
    ) -> None:
        with make_backend() as backend:
            with backend.open() as adapter:
                adapter.create_store(record)
                assert adapter.read_store(record.name) == record
                assert adapter.list_stores() == [record.info]
            with backend.open() as reopened:
                assert reopened.read_store(record.name) == record

    def test_tricky_values_round_trip_exactly(self, adapter: Adapter) -> None:
        variables = {
            "EMPTY": "",
            "SPACES": "  padded  ",
            "MULTILINE": "-----BEGIN KEY-----\r\nabc==\n-----END KEY-----\n",
            "QUOTES": 'it\'s "quoted" `here`',
            "SHELL": "$HOME ${HOME} $(id) ; rm -rf /",
            "EQUALS": "a=b=c #not a comment",
            "BACKSLASH": "back\\slash\\n\\u0041",
            "UNICODE": "äöü ✓ 😀 \u2028 \u200b",
            "CONTROL": "\x01\x1b[31m\x7f",
            "Mixed_Case_9": "case matters",
            "mixed_case_9": "different variable",
        }
        record = _plain(variables=variables)
        adapter.create_store(record)

        read = adapter.read_store("base")

        assert read.variables == variables

    def test_timestamps_round_trip_as_aware_utc_with_microseconds(self, adapter: Adapter) -> None:
        plus_five = timezone(timedelta(hours=5, minutes=30))
        created_at = datetime(1999, 12, 31, 23, 59, 59, 999999, tzinfo=plus_five)
        updated_at = datetime(2038, 1, 19, 3, 14, 8, 1, tzinfo=UTC)
        adapter.create_store(_plain(created_at=created_at, updated_at=updated_at))

        read = adapter.read_store("base")
        info = adapter.list_stores()[0]

        for value, expected in (
            (read.created_at, created_at),
            (read.updated_at, updated_at),
            (info.created_at, created_at),
            (info.updated_at, updated_at),
        ):
            assert value == expected
            assert value.utcoffset() == timedelta(0)
            assert value.microsecond == expected.astimezone(UTC).microsecond

    def test_create_existing_store_raises_and_keeps_the_original(self, adapter: Adapter) -> None:
        original = _plain(variables={"A": "original"})
        adapter.create_store(original)

        with pytest.raises(StoreExistsError):
            adapter.create_store(_sealed("base"))

        assert adapter.read_store("base") == original

    @pytest.mark.parametrize("revision", [2, 5])
    def test_create_with_revision_other_than_one_raises_and_creates_nothing(
        self, adapter: Adapter, revision: int
    ) -> None:
        with pytest.raises(ValidationError):
            adapter.create_store(_plain(revision=revision, updated_at=_T1))

        assert adapter.list_stores() == []

    def test_racing_creates_let_exactly_one_win(self, backend: Backend) -> None:
        # Opened once up front, so that first-time setup is not part of the race.
        with backend.open() as adapter:
            assert adapter.list_stores() == []
        records = [_plain(variables={"RACER": str(index)}) for index in range(_RACERS)]
        attempts = iter(records)
        lock = threading.Lock()

        def create(racer: Adapter) -> StoreRecord:
            with lock:
                record = next(attempts)
            racer.create_store(record)
            return record

        results = _race(backend, create)

        winners = [result for result in results if isinstance(result, StoreRecord)]
        losers = [result for result in results if isinstance(result, StoreExistsError)]
        assert len(winners) == 1
        assert len(losers) == _RACERS - 1
        with backend.open() as adapter:
            assert adapter.read_store("base") == winners[0]

    def test_read_missing_store_raises_not_found(self, adapter: Adapter) -> None:
        adapter.create_store(_plain("other"))

        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")

    def test_stores_are_independent(self, adapter: Adapter) -> None:
        first = _plain("first", variables={"A": "1"})
        second = _sealed("second")
        adapter.create_store(first)
        adapter.create_store(second)
        adapter.write_store(_next(first, A="2"), expected_revision=1)
        adapter.delete_store("first")

        assert adapter.read_store("second") == second

    # --- write -----------------------------------------------------------------------------

    def test_write_with_the_current_revision_replaces_the_store(self, adapter: Adapter) -> None:
        original = _plain(variables={"A": "1", "B": "2"})
        adapter.create_store(original)
        replacement = _next(original, A="changed")

        adapter.write_store(replacement, expected_revision=1)

        assert adapter.read_store("base") == replacement
        assert adapter.list_stores() == [replacement.info]

    def test_successive_writes_increment_the_revision(self, adapter: Adapter) -> None:
        record = _plain()
        adapter.create_store(record)
        for value in ("a", "b", "c"):
            written = _next(record, V=value)
            adapter.write_store(written, expected_revision=record.revision)
            record = written

        assert adapter.read_store("base") == record
        assert record.revision == 4

    def test_write_can_replace_plaintext_with_ciphertext_and_switch_key_mode(
        self, adapter: Adapter
    ) -> None:
        adapter.create_store(_plain())
        encrypted = _sealed("base", revision=2)
        rekeyed = _sealed("base", meta=_PASSPHRASE_META, ciphertext=b"other", revision=3)

        adapter.write_store(encrypted, expected_revision=1)
        assert adapter.read_store("base") == encrypted
        adapter.write_store(rekeyed, expected_revision=2)

        assert adapter.read_store("base") == rekeyed
        assert adapter.list_stores()[0].key_mode is KeyMode.PASSPHRASE

    @given(initial=_first_revision_records(), replacement=_any_records())
    def test_write_then_read_round_trips_any_record(
        self, make_backend: BackendFactory, initial: StoreRecord, replacement: StoreRecord
    ) -> None:
        written = dataclasses.replace(replacement, name=initial.name, revision=2)
        with make_backend() as backend:
            with backend.open() as adapter:
                adapter.create_store(initial)
                adapter.write_store(written, expected_revision=1)
                assert adapter.read_store(initial.name) == written
                assert adapter.list_stores() == [written.info]
            with backend.open() as reopened:
                assert reopened.read_store(initial.name) == written

    @pytest.mark.parametrize("expected_revision", [2, 7])
    def test_write_with_a_stale_or_future_revision_raises_and_writes_nothing(
        self, adapter: Adapter, expected_revision: int
    ) -> None:
        original = _plain()
        adapter.create_store(original)
        stale = _plain(variables={"LOST": "update"}, revision=expected_revision + 1)

        with pytest.raises(ConcurrentModificationError):
            adapter.write_store(stale, expected_revision=expected_revision)

        assert adapter.read_store("base") == original

    def test_write_after_a_concurrent_write_raises_and_keeps_the_first(
        self, adapter: Adapter
    ) -> None:
        original = _plain()
        adapter.create_store(original)
        first = _next(original, WRITER="first")
        second = _next(original, WRITER="second")
        adapter.write_store(first, expected_revision=1)

        with pytest.raises(ConcurrentModificationError):
            adapter.write_store(second, expected_revision=1)

        assert adapter.read_store("base") == first

    @pytest.mark.parametrize(
        ("record_revision", "expected_revision"),
        [(1, 1), (3, 1), (1, 0), (2, 0)],
        ids=["same", "skipped", "behind", "zero"],
    )
    def test_write_with_a_wrong_revision_pair_raises_and_writes_nothing(
        self, adapter: Adapter, record_revision: int, expected_revision: int
    ) -> None:
        original = _plain()
        adapter.create_store(original)
        wrong = _plain(variables={"WRONG": "1"}, revision=record_revision)

        with pytest.raises(ValidationError):
            adapter.write_store(wrong, expected_revision=expected_revision)

        assert adapter.read_store("base") == original

    def test_write_with_a_wrong_revision_pair_is_rejected_before_looking_up_the_store(
        self, adapter: Adapter
    ) -> None:
        with pytest.raises(ValidationError):
            adapter.write_store(_plain(revision=3), expected_revision=1)

    def test_write_missing_store_raises_not_found_and_creates_nothing(
        self, adapter: Adapter
    ) -> None:
        with pytest.raises(StoreNotFoundError):
            adapter.write_store(_plain(revision=2), expected_revision=1)

        assert adapter.list_stores() == []

    def test_two_instances_writing_the_same_revision_let_exactly_one_win(
        self, backend: Backend
    ) -> None:
        original = _plain()
        with backend.open() as first, backend.open() as second:
            first.create_store(original)
            read_by_first = first.read_store("base")
            read_by_second = second.read_store("base")
            from_first = _next(read_by_first, WRITER="first")
            from_second = _next(read_by_second, WRITER="second")

            first.write_store(from_first, expected_revision=read_by_first.revision)
            with pytest.raises(ConcurrentModificationError):
                second.write_store(from_second, expected_revision=read_by_second.revision)

            assert second.read_store("base") == from_first

    def test_racing_writes_on_the_same_revision_let_exactly_one_win(self, backend: Backend) -> None:
        original = _plain()
        with backend.open() as adapter:
            adapter.create_store(original)
        writes = [_next(original, RACER=str(index)) for index in range(_RACERS)]
        attempts = iter(writes)
        lock = threading.Lock()

        def write(racer: Adapter) -> StoreRecord:
            with lock:
                record = next(attempts)
            racer.write_store(record, expected_revision=1)
            return record

        results = _race(backend, write)

        winners = [result for result in results if isinstance(result, StoreRecord)]
        losers = [result for result in results if isinstance(result, ConcurrentModificationError)]
        assert len(winners) == 1
        assert len(losers) == _RACERS - 1
        with backend.open() as adapter:
            assert adapter.read_store("base") == winners[0]

    # --- delete ----------------------------------------------------------------------------

    def test_delete_removes_the_store(self, adapter: Adapter) -> None:
        adapter.create_store(_plain())
        adapter.create_store(_plain("kept"))

        adapter.delete_store("base")

        assert [info.name for info in adapter.list_stores()] == ["kept"]
        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")

    def test_delete_missing_store_raises_not_found(self, adapter: Adapter) -> None:
        with pytest.raises(StoreNotFoundError):
            adapter.delete_store("base")

    def test_delete_twice_raises_not_found(self, adapter: Adapter) -> None:
        adapter.create_store(_plain())
        adapter.delete_store("base")

        with pytest.raises(StoreNotFoundError):
            adapter.delete_store("base")

    def test_write_after_delete_raises_not_found(self, adapter: Adapter) -> None:
        original = _plain()
        adapter.create_store(original)
        adapter.delete_store("base")

        with pytest.raises(StoreNotFoundError):
            adapter.write_store(_next(original, A="1"), expected_revision=1)

        assert adapter.list_stores() == []

    def test_delete_then_create_starts_again_at_revision_one(self, adapter: Adapter) -> None:
        original = _plain(variables={"OLD": "1"})
        adapter.create_store(original)
        adapter.write_store(_next(original, OLD="2"), expected_revision=1)
        adapter.delete_store("base")
        recreated = _sealed("base")

        adapter.create_store(recreated)

        assert adapter.read_store("base") == recreated
        assert adapter.list_stores() == [recreated.info]

    # --- store name validation (defense in depth) ------------------------------------------

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_read_rejects_an_invalid_store_name(self, adapter: Adapter, name: str) -> None:
        with pytest.raises(ValidationError):
            adapter.read_store(name)

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_delete_rejects_an_invalid_store_name(self, adapter: Adapter, name: str) -> None:
        with pytest.raises(ValidationError):
            adapter.delete_store(name)

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_create_rejects_a_forged_store_name_and_creates_nothing(
        self, adapter: Adapter, name: str
    ) -> None:
        with pytest.raises(ValidationError):
            adapter.create_store(_forge_name(_plain(), name))

        assert adapter.list_stores() == []

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_write_rejects_a_forged_store_name_and_writes_nothing(
        self, adapter: Adapter, name: str
    ) -> None:
        adapter.create_store(_plain())

        with pytest.raises(ValidationError):
            adapter.write_store(_forge_name(_plain(revision=2), name), expected_revision=1)

        assert adapter.list_stores() == [_plain().info]

    # --- instances, persistence and setup modes --------------------------------------------

    def test_stores_persist_across_instances(self, backend: Backend) -> None:
        record = _plain()
        sealed = _sealed()
        with backend.open() as adapter:
            adapter.create_store(record)
            adapter.create_store(sealed)
            written = _next(record, A="1")
            adapter.write_store(written, expected_revision=1)

        with backend.open() as reopened:
            assert reopened.read_store("base") == written
            assert reopened.list_stores() == [written.info, sealed.info]
            reopened.delete_store("secret")

        with backend.open() as again:
            assert again.list_stores() == [written.info]

    def test_open_instances_see_each_others_changes(self, backend: Backend) -> None:
        record = _plain()
        with backend.open() as first, backend.open() as second:
            assert second.list_stores() == []
            first.create_store(record)
            assert second.read_store("base") == record
            written = _next(record, A="1")
            second.write_store(written, expected_revision=1)
            assert first.read_store("base") == written
            first.delete_store("base")
            assert second.list_stores() == []

    @pytest.mark.parametrize("setup", list(SetupMode))
    def test_every_setup_mode_gives_a_working_adapter(
        self, backend: Backend, setup: SetupMode
    ) -> None:
        record = _plain()
        with backend.open(setup=setup) as adapter:
            assert adapter.list_stores() == []
            adapter.create_store(record)
            assert adapter.read_store("base") == record

        with backend.open(setup=setup) as reopened:
            assert reopened.read_store("base") == record

    def test_open_returns_a_new_instance_each_time(self, backend: Backend) -> None:
        with backend.open() as first, backend.open() as second:
            assert first is not second

    # --- context manager and close ---------------------------------------------------------

    def test_enter_returns_the_adapter_itself(self, backend: Backend) -> None:
        adapter = backend.open()
        try:
            with adapter as entered:
                assert entered is adapter
        finally:
            adapter.close()

    def test_exit_does_not_suppress_exceptions(self, backend: Backend) -> None:
        def fail_inside() -> None:
            with backend.open():
                message = "boom"
                raise RuntimeError(message)

        with pytest.raises(RuntimeError, match="boom"):
            fail_inside()

    @pytest.mark.parametrize(
        "operation",
        [
            lambda adapter: adapter.list_stores(),
            lambda adapter: adapter.create_store(_plain("new")),
            lambda adapter: adapter.read_store("base"),
            lambda adapter: adapter.write_store(_plain(revision=2), expected_revision=1),
            lambda adapter: adapter.delete_store("base"),
        ],
        ids=["list", "create", "read", "write", "delete"],
    )
    def test_leaving_the_context_closes_the_adapter(
        self, backend: Backend, operation: Callable[[Adapter], object]
    ) -> None:
        with backend.open() as adapter:
            adapter.create_store(_plain())

        with pytest.raises(BackendError):
            operation(adapter)

        with backend.open() as reopened:
            assert reopened.read_store("base") == _plain()

    def test_close_is_idempotent_and_closes_the_adapter(self, backend: Backend) -> None:
        adapter = backend.open()
        adapter.close()
        adapter.close()

        with pytest.raises(BackendError):
            adapter.list_stores()
