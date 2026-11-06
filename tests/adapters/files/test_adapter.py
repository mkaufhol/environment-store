"""Behaviour of the file adapters beyond the contract suite (spec §3.2, D7, D9, D27)."""

import errno
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.files import (
    JSON_SERIALIZER,
    TOML_SERIALIZER,
    FileAdapter,
    FileSerializer,
    exclusive_lock,
    locking,
    open_json,
    open_toml,
)
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.connection import open_adapter
from environment_store.core.errors import (
    BackendError,
    StoreExistsError,
    StoreNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from environment_store.core.models import Cipher, CipherMeta, KeyMode, StoreInfo, StoreRecord

_T0: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_CANARY: Final[str] = "canary-value-never-in-messages"
_SERIALIZERS: Final = [
    pytest.param(JSON_SERIALIZER, id="json"),
    pytest.param(TOML_SERIALIZER, id="toml"),
]


def _plain(name: str = "base", **variables: str) -> StoreRecord:
    return StoreRecord.plain(name=name, variables=variables or {"HOST": "x"}, created_at=_T0)


def _next(record: StoreRecord, **variables: str) -> StoreRecord:
    return StoreRecord.plain(
        name=record.name,
        variables=variables,
        revision=record.revision + 1,
        created_at=record.created_at,
        updated_at=record.updated_at + timedelta(seconds=1),
    )


def _sealed(name: str = "secret") -> StoreRecord:
    return StoreRecord.sealed(
        name=name,
        ciphertext=b"opaque",
        cipher_meta=CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE),
        created_at=_T0,
    )


@pytest.fixture(params=_SERIALIZERS)
def serializer(request: pytest.FixtureRequest) -> FileSerializer:
    return request.param


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path / "stores"


@pytest.fixture
def adapter(directory: Path, serializer: FileSerializer) -> Iterator[FileAdapter]:
    with FileAdapter(directory, serializer=serializer) as adapter:
        yield adapter


def _file(directory: Path, serializer: FileSerializer, name: str = "base") -> Path:
    return directory / f"{name}{serializer.extension}"


def _leftovers(directory: Path) -> list[str]:
    """Temporary files that were not cleaned up."""
    return sorted(path.name for path in directory.iterdir() if path.suffix == ".tmp")


# --- opening ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("opener", "scheme", "serializer"),
    [(open_json, "json", JSON_SERIALIZER), (open_toml, "toml", TOML_SERIALIZER)],
)
def test_open_parses_the_url_into_directory_and_serializer(
    tmp_path: Path,
    opener: Callable[..., FileAdapter],
    scheme: str,
    serializer: FileSerializer,
) -> None:
    with opener(f"{scheme}://{tmp_path}") as adapter:
        assert adapter.directory == tmp_path
        assert adapter.serializer is serializer


@pytest.mark.parametrize(("opener", "url"), [(open_json, "toml:///x"), (open_toml, "json:///x")])
def test_open_rejects_the_other_scheme(opener: Callable[..., FileAdapter], url: str) -> None:
    with pytest.raises(ValidationError):
        opener(url)


@pytest.mark.parametrize("scheme", ["json", "toml"])
def test_connection_registry_opens_the_file_adapters(tmp_path: Path, scheme: str) -> None:
    with open_adapter(f"{scheme}://{tmp_path}", setup=SetupMode.NONE) as adapter:
        adapter.create_store(_plain())

    assert (tmp_path / f"base.{scheme}").is_file()


# --- directory --------------------------------------------------------------------------------


def test_missing_directory_lists_nothing_and_is_not_created(
    adapter: FileAdapter, directory: Path
) -> None:
    assert adapter.list_stores() == []
    with pytest.raises(StoreNotFoundError):
        adapter.read_store("base")
    with pytest.raises(StoreNotFoundError):
        adapter.write_store(_next(_plain()), expected_revision=1)
    with pytest.raises(StoreNotFoundError):
        adapter.delete_store("base")

    assert not directory.exists()


def test_directory_is_created_with_parents_on_first_write(
    tmp_path: Path, serializer: FileSerializer
) -> None:
    directory = tmp_path / "a" / "b" / "c"

    with FileAdapter(directory, serializer=serializer) as adapter:
        adapter.create_store(_plain())

    assert _file(directory, serializer).is_file()


def test_one_file_per_store_named_after_the_store(
    adapter: FileAdapter, directory: Path, serializer: FileSerializer
) -> None:
    adapter.create_store(_plain("first"))
    adapter.create_store(_sealed("second-2"))

    stores = sorted(path.name for path in directory.iterdir() if not path.name.startswith("."))

    assert stores == [f"first{serializer.extension}", f"second-2{serializer.extension}"]


def test_store_files_are_readable_by_the_owner_only(
    adapter: FileAdapter, directory: Path, serializer: FileSerializer
) -> None:
    adapter.create_store(_plain())
    adapter.write_store(_next(_plain(), A="1"), expected_revision=1)

    mode = stat.S_IMODE(_file(directory, serializer).stat().st_mode)

    assert mode == 0o600


@pytest.mark.parametrize(
    "operation",
    [
        lambda adapter: adapter.list_stores(),
        lambda adapter: adapter.create_store(_plain()),
        lambda adapter: adapter.read_store("base"),
        lambda adapter: adapter.write_store(_next(_plain()), expected_revision=1),
        lambda adapter: adapter.delete_store("base"),
    ],
    ids=["list", "create", "read", "write", "delete"],
)
def test_directory_that_is_a_file_raises_backend_error(
    tmp_path: Path, serializer: FileSerializer, operation: Callable[[Adapter], object]
) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("", encoding="utf-8")

    with (
        FileAdapter(occupied, serializer=serializer) as adapter,
        pytest.raises(BackendError, match="not-a-directory"),
    ):
        operation(adapter)


# --- listing ignores foreign files ------------------------------------------------------------


def test_listing_ignores_other_extensions_invalid_stems_and_directories(
    adapter: FileAdapter, directory: Path, serializer: FileSerializer
) -> None:
    adapter.create_store(_plain())
    other = ".toml" if serializer.extension == ".json" else ".json"
    for name in (
        f"other{other}",
        "notes.txt",
        "README",
        f"Upper{serializer.extension}",
        f"a.b{serializer.extension}",
        f"-dash{serializer.extension}",
        f".hidden{serializer.extension}",
        f"{'x' * 64}{serializer.extension}",
        f"upper-ext{serializer.extension.upper()}",
    ):
        (directory / name).write_text("not a store", encoding="utf-8")
    (directory / f"folder{serializer.extension}").mkdir()

    assert [info.name for info in adapter.list_stores()] == ["base"]


def _case_variants(serializer: FileSerializer) -> list[str]:
    return [f"Base{serializer.extension}", f"base{serializer.extension.upper()}"]


def _ignores_case(directory: Path) -> bool:
    """Whether the file system of `directory` treats names that differ in case as one name."""
    probe = directory / "case-probe"
    probe.touch()
    try:
        return (directory / "CASE-PROBE").exists()
    finally:
        probe.unlink()


@pytest.mark.parametrize("variant", [0, 1], ids=["upper-stem", "upper-extension"])
def test_case_variant_of_a_store_file_is_neither_listed_read_written_nor_deleted(
    adapter: FileAdapter, directory: Path, serializer: FileSerializer, variant: int
) -> None:
    # A valid store file under a name that differs from `base.<ext>` only in case: on a
    # case-insensitive file system (macOS, Windows) `base.<ext>` would open it.
    adapter.create_store(_plain())
    foreign = directory / _case_variants(serializer)[variant]
    _file(directory, serializer).rename(foreign)
    original = foreign.read_bytes()

    assert adapter.list_stores() == []
    for operation in (
        lambda: adapter.read_store("base"),
        lambda: adapter.write_store(_next(_plain(), A="new"), expected_revision=1),
        lambda: adapter.delete_store("base"),
    ):
        with pytest.raises(StoreNotFoundError):
            operation()

    assert foreign.read_bytes() == original
    assert [path.name for path in directory.iterdir() if not path.name.startswith(".")] == [
        foreign.name
    ]


@pytest.mark.parametrize("variant", [0, 1], ids=["upper-stem", "upper-extension"])
def test_create_next_to_a_case_variant_never_touches_it(
    adapter: FileAdapter, directory: Path, serializer: FileSerializer, variant: int
) -> None:
    directory.mkdir()
    foreign = directory / _case_variants(serializer)[variant]
    foreign.write_text("not a store, user notes", encoding="utf-8")
    # Case-insensitive: the names collide, so create must refuse; case-sensitive: both coexist.
    refused = pytest.raises(BackendError, match="case") if _ignores_case(directory) else None

    with refused or nullcontext():
        adapter.create_store(_plain())

    assert foreign.read_text(encoding="utf-8") == "not a store, user notes"


def test_create_refuses_a_name_taken_by_a_case_variant(
    adapter: FileAdapter,
    directory: Path,
    serializer: FileSerializer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulates a case-insensitive file system on any platform: the link finds "base.<ext>"
    # taken although no entry has exactly that name.
    directory.mkdir()
    foreign = directory / _case_variants(serializer)[0]
    foreign.write_text("not a store", encoding="utf-8")
    monkeypatch.setattr(os, "link", _failing(FileExistsError(errno.EEXIST, "File exists")))

    with pytest.raises(BackendError, match="differs only in case") as caught:
        adapter.create_store(_plain())

    assert not isinstance(caught.value, StoreExistsError)
    assert isinstance(caught.value.__cause__, FileExistsError)
    monkeypatch.undo()
    assert foreign.read_text(encoding="utf-8") == "not a store"
    assert _leftovers(directory) == []


@pytest.mark.parametrize(
    "operation",
    [
        lambda adapter: adapter.write_store(_next(_plain(), A="new"), expected_revision=1),
        lambda adapter: adapter.delete_store("base"),
    ],
    ids=["write", "delete"],
)
def test_write_and_delete_recheck_the_store_file_under_the_lock(
    adapter: FileAdapter,
    directory: Path,
    serializer: FileSerializer,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[Adapter], object],
) -> None:
    # The store is replaced by a case variant while the operation waits for the lock.
    adapter.create_store(_plain())
    foreign = directory / _case_variants(serializer)[0]
    real_lock = locking.exclusive_lock

    def swap_then_lock(path: Path, *, timeout: float) -> AbstractContextManager[None]:
        _file(directory, serializer).rename(directory / "moved")
        foreign.write_text("not a store", encoding="utf-8")
        return real_lock(path, timeout=timeout)

    monkeypatch.setattr("environment_store.adapters.files.adapter.exclusive_lock", swap_then_lock)

    with pytest.raises(StoreNotFoundError):
        operation(adapter)

    assert foreign.read_text(encoding="utf-8") == "not a store"


def test_json_and_toml_stores_in_one_directory_are_independent(directory: Path) -> None:
    with (
        FileAdapter(directory, serializer=JSON_SERIALIZER) as json_adapter,
        FileAdapter(directory, serializer=TOML_SERIALIZER) as toml_adapter,
    ):
        json_adapter.create_store(_plain(A="json"))
        toml_adapter.create_store(_plain(A="toml"))
        json_adapter.delete_store("base")

        assert json_adapter.list_stores() == []
        assert toml_adapter.read_store("base") == _plain(A="toml")


def test_listing_skips_a_store_deleted_while_listing(
    adapter: FileAdapter, serializer: FileSerializer, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter.create_store(_plain("gone"))
    adapter.create_store(_plain("kept"))
    read_bytes = Path.read_bytes

    def deleted_meanwhile(path: Path) -> bytes:
        if path.name == f"gone{serializer.extension}":
            raise FileNotFoundError(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deleted_meanwhile)

    assert [info.name for info in adapter.list_stores()] == ["kept"]


def test_delete_of_a_store_deleted_while_waiting_for_the_lock_raises_not_found(
    adapter: FileAdapter, serializer: FileSerializer, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter.create_store(_plain())
    unlink = Path.unlink

    def deleted_meanwhile(path: Path, *, missing_ok: bool = False) -> None:
        if path.name == f"base{serializer.extension}":
            unlink(path)
            raise FileNotFoundError(path)
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", deleted_meanwhile)

    with pytest.raises(StoreNotFoundError) as caught:
        adapter.delete_store("base")

    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_read_of_a_store_deleted_after_the_check_chains_the_os_error(
    adapter: FileAdapter, serializer: FileSerializer, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter.create_store(_plain())
    read_bytes = Path.read_bytes

    def deleted_meanwhile(path: Path) -> bytes:
        if path.name == f"base{serializer.extension}":
            raise FileNotFoundError(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", deleted_meanwhile)

    with pytest.raises(StoreNotFoundError) as caught:
        adapter.read_store("base")

    assert isinstance(caught.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("missing", ["file", "directory"])
def test_missing_store_raises_not_found(
    adapter: FileAdapter, directory: Path, missing: str
) -> None:
    if missing == "file":
        directory.mkdir()
    for operation in (
        lambda: adapter.read_store("base"),
        lambda: adapter.write_store(_next(_plain()), expected_revision=1),
        lambda: adapter.delete_store("base"),
    ):
        with pytest.raises(StoreNotFoundError):
            operation()


# --- store name path safety (D27) ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["../outside", "..", "a/../../outside", "/etc/abs", "sub/base"])
def test_traversal_names_never_reach_files_outside_the_directory(
    tmp_path: Path, serializer: FileSerializer, name: str
) -> None:
    directory = tmp_path / "stores"
    outside = tmp_path / f"outside{serializer.extension}"
    with FileAdapter(tmp_path, serializer=serializer) as parent:
        parent.create_store(_plain("outside"))
    original = outside.read_bytes()

    with FileAdapter(directory, serializer=serializer) as adapter:
        adapter.create_store(_plain())
        forged = _plain()
        object.__setattr__(forged, "name", name)
        for operation in (
            lambda: adapter.read_store(name),
            lambda: adapter.delete_store(name),
            lambda: adapter.create_store(forged),
            lambda: adapter.write_store(_next(forged), expected_revision=1),
        ):
            with pytest.raises(ValidationError):
                operation()

    assert outside.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [".outside" + serializer.extension + ".lock", outside.name, "stores"]
    )
    assert [path.name for path in directory.iterdir() if not path.name.startswith(".")] == [
        f"base{serializer.extension}"
    ]


# --- atomicity ----------------------------------------------------------------------------------


def _failing(error: OSError) -> Callable[..., None]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    return fail


def test_failed_replace_keeps_the_old_file_and_removes_the_temp_file(
    adapter: FileAdapter,
    directory: Path,
    serializer: FileSerializer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _plain()
    adapter.create_store(original)
    monkeypatch.setattr(os, "replace", _failing(OSError(28, "No space left on device")))

    with pytest.raises(BackendError, match="No space left"):
        adapter.write_store(_next(original, A="new"), expected_revision=1)

    monkeypatch.undo()
    assert adapter.read_store("base") == original
    assert _leftovers(directory) == []


def test_failed_fsync_writes_nothing_and_removes_the_temp_file(
    adapter: FileAdapter, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory.mkdir()
    monkeypatch.setattr(os, "fsync", _failing(OSError(5, "Input/output error")))

    with pytest.raises(BackendError, match="Input/output error"):
        adapter.create_store(_plain())

    monkeypatch.undo()
    assert adapter.list_stores() == []
    assert _leftovers(directory) == []


def test_failed_link_on_create_writes_nothing_and_removes_the_temp_file(
    adapter: FileAdapter, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "link", _failing(OSError(errno.EIO, "Input/output error")))

    with pytest.raises(BackendError, match="Input/output error"):
        adapter.create_store(_plain())

    monkeypatch.undo()
    assert adapter.list_stores() == []
    assert _leftovers(directory) == []


_NO_HARD_LINKS: Final = [
    pytest.param(errno.ENOTSUP, id="ENOTSUP"),
    pytest.param(errno.EPERM, id="EPERM"),
    pytest.param(errno.ENOSYS, id="ENOSYS"),
]


@pytest.mark.parametrize("code", _NO_HARD_LINKS)
def test_create_works_on_a_file_system_without_hard_links(
    adapter: FileAdapter, directory: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    # exFAT, FAT and some network mounts: os.link fails, os.replace and flock work.
    monkeypatch.setattr(os, "link", _failing(OSError(code, os.strerror(code))))

    adapter.create_store(_plain())
    with pytest.raises(StoreExistsError):
        adapter.create_store(_plain(A="second"))

    assert adapter.read_store("base") == _plain()
    assert _leftovers(directory) == []


def test_create_without_hard_links_refuses_a_case_variant(
    adapter: FileAdapter,
    directory: Path,
    serializer: FileSerializer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory.mkdir()
    foreign = directory / _case_variants(serializer)[0]
    foreign.write_text("not a store", encoding="utf-8")
    monkeypatch.setattr(os, "link", _failing(OSError(errno.ENOTSUP, "Operation not supported")))
    exists = Path.exists

    def ignoring_case(path: Path, *, follow_symlinks: bool = True) -> bool:
        if path.name == f"base{serializer.extension}":
            return True
        return exists(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "exists", ignoring_case)

    with pytest.raises(BackendError, match="differs only in case"):
        adapter.create_store(_plain())

    monkeypatch.undo()
    assert foreign.read_text(encoding="utf-8") == "not a store"
    assert _leftovers(directory) == []


def test_interrupted_write_removes_the_temp_file(
    adapter: FileAdapter, directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _plain()
    adapter.create_store(original)

    def interrupt(*_args: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        adapter.write_store(_next(original), expected_revision=1)

    monkeypatch.undo()
    assert adapter.read_store("base") == original
    assert _leftovers(directory) == []


# --- locking ------------------------------------------------------------------------------------


def test_lock_excludes_a_second_holder_until_released(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"

    with (
        exclusive_lock(path, timeout=1.0),
        pytest.raises(BackendError, match=r"x\.lock"),
        exclusive_lock(path, timeout=0.05),
    ):
        pass
    with exclusive_lock(path, timeout=0.05):
        pass


def test_lock_file_that_cannot_be_opened_raises_backend_error(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "x.lock"

    with pytest.raises(BackendError, match=r"x\.lock") as caught, exclusive_lock(path, timeout=1.0):
        pass

    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_lock_that_fails_raises_backend_error_and_closes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []
    open_ = os.open

    def tracking_open(path: Path, flags: int, mode: int) -> int:
        opened.append(open_(path, flags, mode))
        return opened[-1]

    monkeypatch.setattr(locking, "_try_lock", _failing(OSError(errno.ENOLCK, "No locks")))
    monkeypatch.setattr(os, "open", tracking_open)

    with (
        pytest.raises(BackendError, match="No locks") as caught,
        exclusive_lock(tmp_path / "x.lock", timeout=1.0),
    ):
        pass

    monkeypatch.undo()
    assert isinstance(caught.value.__cause__, OSError)
    assert len(opened) == 1
    with pytest.raises(OSError, match="Bad file descriptor"):
        os.fstat(opened[0])


def test_errors_inside_the_locked_block_pass_through_unchanged(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError), exclusive_lock(tmp_path / "x.lock", timeout=1.0):
        raise FileNotFoundError


@pytest.mark.parametrize(
    "operation",
    [
        lambda adapter: adapter.create_store(_plain()),
        lambda adapter: adapter.write_store(_next(_plain(), A="new"), expected_revision=1),
        lambda adapter: adapter.delete_store("base"),
    ],
    ids=["create", "write", "delete"],
)
def test_store_locked_by_another_writer_times_out_and_changes_nothing(
    directory: Path,
    serializer: FileSerializer,
    operation: Callable[[Adapter], object],
) -> None:
    with FileAdapter(directory, serializer=serializer) as setup:
        setup.create_store(_plain())
    lock = directory / f".base{serializer.extension}.lock"

    with (
        exclusive_lock(lock, timeout=1.0),
        FileAdapter(directory, serializer=serializer, lock_timeout=0.05) as adapter,
    ):
        with pytest.raises(BackendError, match="lock"):
            operation(adapter)
        assert adapter.read_store("base") == _plain()


def test_lock_on_one_store_does_not_block_another(
    directory: Path, serializer: FileSerializer
) -> None:
    with FileAdapter(directory, serializer=serializer, lock_timeout=0.05) as adapter:
        adapter.create_store(_plain())
        with exclusive_lock(directory / f".base{serializer.extension}.lock", timeout=1.0):
            adapter.create_store(_plain("other"))

        assert [info.name for info in adapter.list_stores()] == ["base", "other"]


# --- corrupt and foreign files ------------------------------------------------------------------

_JSON_HEADER: Final[str] = (
    '"format": 1, "encrypted": false, "revision": 1, '
    '"created_at": "2026-11-06T10:00:00Z", "updated_at": "2026-11-06T10:00:00Z"'
)
_TOML_HEADER: Final[str] = (
    "format = 1\nencrypted = false\nrevision = 1\n"
    "created_at = 2026-11-06T10:00:00Z\nupdated_at = 2026-11-06T10:00:00Z\n"
)
_SEALED_JSON: Final[str] = (
    '{"format": 1, "encrypted": true, "revision": 1, '
    '"created_at": "2026-11-06T10:00:00Z", "updated_at": "2026-11-06T10:00:00Z", '
    '"payload": "AAEC", "cipher": %s}'
)
_SEALED_TOML: Final[str] = (
    "format = 1\nencrypted = true\nrevision = 1\n"
    "created_at = 2026-11-06T10:00:00Z\nupdated_at = 2026-11-06T10:00:00Z\n"
    'payload = "AAEC"\n[cipher]\n%s\n'
)

_KEYFILE_TABLE: Final[tuple[str, str]] = (
    '{"name": "aes256gcm", "mode": "keyfile"}',
    'name = "aes256gcm"\nmode = "keyfile"',
)

# (JSON content, TOML content) of files whose header is broken: every operation that reads the
# file fails, listing included.
_CORRUPT_HEADER: Final[dict[str, tuple[str, str | None]]] = {
    "syntax": (f'{{"A": "{_CANARY}"', f'A = "{_CANARY}'),
    "not-a-table": (f'["{_CANARY}"]', None),
    "no-format": (f'{{"variables": {{"A": "{_CANARY}"}}}}', f'[variables]\nA = "{_CANARY}"\n'),
    "encrypted-not-bool": (
        "{" + _JSON_HEADER.replace("false", '"no"') + ', "variables": {}}',
        _TOML_HEADER.replace("false", '"no"') + "[variables]\n",
    ),
    "missing-variables": ("{" + _JSON_HEADER + "}", _TOML_HEADER),
    "unknown-key": (
        "{" + _JSON_HEADER + ', "variables": {}, "extra": 1}',
        _TOML_HEADER + "extra = 1\n[variables]\n",
    ),
    "flag-says-plain-but-sealed": (
        "{" + _JSON_HEADER + f', "payload": "AAEC", "cipher": {_KEYFILE_TABLE[0]}}}',
        _TOML_HEADER + f'payload = "AAEC"\n[cipher]\n{_KEYFILE_TABLE[1]}\n',
    ),
    "revision-zero": (
        "{" + _JSON_HEADER.replace('"revision": 1', '"revision": 0') + ', "variables": {}}',
        _TOML_HEADER.replace("revision = 1", "revision = 0") + "[variables]\n",
    ),
    "revision-text": (
        "{" + _JSON_HEADER.replace('"revision": 1', '"revision": "1"') + ', "variables": {}}',
        _TOML_HEADER.replace("revision = 1", 'revision = "1"') + "[variables]\n",
    ),
    "naive-timestamp": (
        "{" + _JSON_HEADER.replace('10:00:00Z"', '10:00:00"', 1) + ', "variables": {}}',
        _TOML_HEADER.replace("10:00:00Z", "10:00:00", 1) + "[variables]\n",
    ),
    # Valid timestamps whose UTC equivalent lies outside the datetime range.
    "timestamp-overflow": (
        "{"
        + _JSON_HEADER.replace("2026-11-06T10:00:00Z", "9999-12-31T23:59:59-01:00")
        + ', "variables": {}}',
        _TOML_HEADER.replace("2026-11-06T10:00:00Z", "0001-01-01T00:00:00+01:00") + "[variables]\n",
    ),
    "created-after-updated": (
        "{" + _JSON_HEADER.replace("2026", "2027", 1) + ', "variables": {}}',
        _TOML_HEADER.replace("2026", "2027", 1) + "[variables]\n",
    ),
}
# Files with a valid header but a broken payload: reading fails, listing does not look at it.
_CORRUPT_PAYLOAD: Final[dict[str, tuple[str, str]]] = {
    "variables-not-a-table": (
        "{" + _JSON_HEADER + f', "variables": "{_CANARY}"}}',
        _TOML_HEADER + f'variables = "{_CANARY}"\n',
    ),
    "value-not-a-string": (
        "{" + _JSON_HEADER + ', "variables": {"A": 1}}',
        _TOML_HEADER + "[variables]\nA = 1\n",
    ),
    "invalid-variable-name": (
        "{" + _JSON_HEADER + f', "variables": {{"1A": "{_CANARY}"}}}}',
        _TOML_HEADER + f'[variables]\n1A = "{_CANARY}"\n',
    ),
    "nul-in-value": (
        "{" + _JSON_HEADER + ', "variables": {"A": "x\\u0000y"}}',
        _TOML_HEADER + '[variables]\nA = "x\\u0000y"\n',
    ),
    "payload-not-base64": (
        _SEALED_JSON.replace('"AAEC"', '"not base64!"') % _KEYFILE_TABLE[0],
        _SEALED_TOML.replace('"AAEC"', '"not base64!"') % _KEYFILE_TABLE[1],
    ),
    "payload-not-a-string": (
        _SEALED_JSON.replace('"AAEC"', "1") % _KEYFILE_TABLE[0],
        _SEALED_TOML.replace('"AAEC"', "1") % _KEYFILE_TABLE[1],
    ),
}


def _cases(table: dict[str, tuple[str, str | None]] | dict[str, tuple[str, str]]) -> list[object]:
    cases: list[object] = []
    for case, contents in table.items():
        for serializer, content in zip((JSON_SERIALIZER, TOML_SERIALIZER), contents, strict=True):
            if content is not None:
                kind = serializer.extension.removeprefix(".")
                cases.append(pytest.param(serializer, content, id=f"{case}-{kind}"))
    return cases


def _write_store_file(directory: Path, serializer: FileSerializer, content: str) -> Path:
    directory.mkdir(exist_ok=True)
    path = _file(directory, serializer)
    path.write_text(content, encoding="utf-8")
    return path


def _assert_names_file_not_value(error: BaseException, path: Path) -> None:
    assert str(path) in str(error)
    assert _CANARY not in str(error)


@pytest.mark.parametrize(("serializer", "content"), _cases(_CORRUPT_HEADER))
def test_file_with_a_corrupt_header_fails_every_operation_and_is_left_alone(
    directory: Path, serializer: FileSerializer, content: str
) -> None:
    path = _write_store_file(directory, serializer, content)

    with FileAdapter(directory, serializer=serializer) as adapter:
        for operation in (
            adapter.list_stores,
            lambda: adapter.read_store("base"),
            lambda: adapter.write_store(_next(_plain()), expected_revision=1),
        ):
            with pytest.raises(BackendError) as caught:
                operation()
            _assert_names_file_not_value(caught.value, path)

    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize(("serializer", "content"), _cases(_CORRUPT_PAYLOAD))
def test_file_with_a_corrupt_payload_fails_reading_but_not_listing(
    directory: Path, serializer: FileSerializer, content: str
) -> None:
    path = _write_store_file(directory, serializer, content)

    with FileAdapter(directory, serializer=serializer) as adapter:
        with pytest.raises(BackendError) as caught:
            adapter.read_store("base")
        _assert_names_file_not_value(caught.value, path)
        assert [info.name for info in adapter.list_stores()] == ["base"]


@pytest.mark.parametrize(
    ("serializer", "content"),
    [
        pytest.param(JSON_SERIALIZER, "[" * 100_000 + "]" * 100_000, id="json"),
        pytest.param(TOML_SERIALIZER, "a = " + "[" * 100_000 + "]" * 100_000, id="toml"),
    ],
)
def test_deeply_nested_file_raises_backend_error(
    directory: Path, serializer: FileSerializer, content: str
) -> None:
    path = _write_store_file(directory, serializer, content)

    with FileAdapter(directory, serializer=serializer) as adapter:
        with pytest.raises(BackendError) as caught:
            adapter.read_store("base")
        _assert_names_file_not_value(caught.value, path)


def test_file_that_is_not_utf8_raises_backend_error(
    directory: Path, serializer: FileSerializer
) -> None:
    directory.mkdir()
    path = _file(directory, serializer)
    path.write_bytes(b"\xff\xfe\x00")

    with FileAdapter(directory, serializer=serializer) as adapter:
        with pytest.raises(BackendError) as caught:
            adapter.read_store("base")
        _assert_names_file_not_value(caught.value, path)


@pytest.mark.parametrize(
    "contents",
    [
        ('{"format": 2}', "format = 2\n"),
        ('{"format": true}', "format = true\n"),
        ('{"format": "1"}', 'format = "1"\n'),
        ('{"format": 1.0}', "format = 1.0\n"),
    ],
    ids=["two", "bool", "text", "float"],
)
def test_unknown_format_raises_unsupported_format_error_naming_the_file(
    directory: Path, contents: tuple[str, str]
) -> None:
    for serializer, content in zip((JSON_SERIALIZER, TOML_SERIALIZER), contents, strict=True):
        path = _write_store_file(directory, serializer, content)
        with FileAdapter(directory, serializer=serializer) as adapter:
            for operation in (adapter.list_stores, lambda: adapter.read_store("base")):
                with pytest.raises(UnsupportedFormatError, match="format") as caught:
                    operation()
                _assert_names_file_not_value(caught.value, path)


@pytest.mark.parametrize(
    ("serializer", "content"),
    [
        pytest.param(
            JSON_SERIALIZER, _SEALED_JSON % '{"name": "age", "mode": "keyfile"}', id="cipher-json"
        ),
        pytest.param(
            TOML_SERIALIZER, _SEALED_TOML % 'name = "age"\nmode = "keyfile"', id="cipher-toml"
        ),
        pytest.param(
            JSON_SERIALIZER, _SEALED_JSON % '{"name": "aes256gcm", "mode": "hsm"}', id="mode-json"
        ),
        pytest.param(
            TOML_SERIALIZER, _SEALED_TOML % 'name = "aes256gcm"\nmode = "hsm"', id="mode-toml"
        ),
        pytest.param(JSON_SERIALIZER, _SEALED_JSON % '"aes256gcm"', id="not-a-table-json"),
        pytest.param(
            TOML_SERIALIZER,
            _SEALED_TOML.replace("[cipher]\n%s\n", 'cipher = "aes256gcm"\n'),
            id="not-a-table-toml",
        ),
    ],
)
def test_unknown_cipher_fails_reading_but_not_listing(
    directory: Path, serializer: FileSerializer, content: str
) -> None:
    path = _write_store_file(directory, serializer, content)

    with FileAdapter(directory, serializer=serializer) as adapter:
        with pytest.raises(UnsupportedFormatError) as caught:
            adapter.read_store("base")
        _assert_names_file_not_value(caught.value, path)
        assert adapter.list_stores() == [
            StoreInfo(
                name="base",
                encrypted=True,
                key_mode=None,
                revision=1,
                created_at=_T0,
                updated_at=_T0,
            )
        ]
