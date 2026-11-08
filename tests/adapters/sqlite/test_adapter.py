"""SQLite specifics beyond the contract: connection strings, constraints, corrupt rows, threads."""

import os
import sqlite3
import stat
import traceback
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.sqlite import SqliteAdapter, open_sqlite
from environment_store.adapters.sqlite import connection as connection_module
from environment_store.adapters.sqlite.schema import transaction
from environment_store.core.adapter import Adapter, MigratableAdapter, SetupMode
from environment_store.core.connection import open_adapter
from environment_store.core.errors import (
    BackendError,
    StoreNotFoundError,
    UnsupportedFormatError,
)
from environment_store.core.models import MAX_REVISION, Cipher, CipherMeta, KeyMode, StoreRecord
from tests.adapters.sqlite.backend import raw, url_of

_T0: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_TS: Final = "2026-11-06T10:00:00.000000Z"
_META: Final = '{"cipher":"aes256gcm","mode":"keyfile"}'
_INSERT: Final = (
    "INSERT INTO stores (name, encrypted, cipher_meta, variables, ciphertext, revision, "
    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
_VALID_PLAIN: Final[tuple[object, ...]] = ("base", 0, None, "{}", None, 1, _TS, _TS)
_VALID_SEALED: Final[tuple[object, ...]] = ("secret", 1, _META, None, b"\x00", 1, _TS, _TS)

# Rows that break the schema's check constraints: never plaintext and encrypted at once, never
# neither, a 0/1 flag, a revision >= 1, no NULL in required columns.
_INVALID_ROWS: Final[dict[str, tuple[object, ...]]] = {
    "plaintext with ciphertext": ("x", 0, None, "{}", b"\x00", 1, _TS, _TS),
    "plaintext with cipher meta": ("x", 0, _META, "{}", None, 1, _TS, _TS),
    "plaintext without variables": ("x", 0, None, None, None, 1, _TS, _TS),
    "encrypted with variables": ("x", 1, _META, "{}", b"\x00", 1, _TS, _TS),
    "encrypted without ciphertext": ("x", 1, _META, None, None, 1, _TS, _TS),
    "encrypted without cipher meta": ("x", 1, None, None, b"\x00", 1, _TS, _TS),
    "flag other than 0 or 1": ("x", 2, None, "{}", None, 1, _TS, _TS),
    "revision zero": ("x", 0, None, "{}", None, 0, _TS, _TS),
    "missing name": (None, 0, None, "{}", None, 1, _TS, _TS),
    "missing created_at": ("x", 0, None, "{}", None, 1, None, _TS),
    "missing updated_at": ("x", 0, None, "{}", None, 1, _TS, None),
}


def _plain(name: str = "base") -> StoreRecord:
    return StoreRecord.plain(name=name, variables={"HOST": "localhost"}, created_at=_T0)


def _next(record: StoreRecord) -> StoreRecord:
    return StoreRecord.plain(
        name=record.name,
        variables={"HOST": "remote"},
        revision=record.revision + 1,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "envs.db"


@pytest.fixture
def set_up_path(path: Path) -> Path:
    """A database file with the current schema and no stores."""
    with open_sqlite(url_of(path)) as adapter:
        adapter.migrate()
    return path


# --- opening -------------------------------------------------------------------------------


def test_sqlite_scheme_opens_a_migratable_sqlite_adapter(path: Path) -> None:
    with open_adapter(url_of(path)) as adapter:
        assert isinstance(adapter, SqliteAdapter)
        assert isinstance(adapter, MigratableAdapter)
        assert isinstance(adapter, Adapter)
        assert adapter.path == path


def test_relative_path_is_resolved_against_the_working_directory_on_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with open_sqlite("sqlite:///data.db") as adapter:
        adapter.create_store(_plain())
        monkeypatch.chdir(tmp_path.parent)
        assert adapter.read_store("base") == _plain()

    assert adapter.path == tmp_path / "data.db"
    assert (tmp_path / "data.db").is_file()


def test_memory_like_file_name_is_a_real_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with open_sqlite("sqlite:///:memory:") as adapter:
        adapter.create_store(_plain())

    with open_sqlite("sqlite:///:memory:") as reopened:
        assert reopened.read_store("base") == _plain()


@pytest.fixture
def umask_022() -> Iterator[None]:
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.usefixtures("umask_022")
def test_a_new_database_file_is_readable_by_the_owner_only(path: Path) -> None:
    # Plaintext stores live in the file; like the file backend's store files it is 0600.
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.usefixtures("umask_022")
def test_an_existing_database_file_keeps_its_mode(path: Path) -> None:
    path.touch(mode=0o640)
    path.chmod(0o640)

    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


# --- missing files and directories ---------------------------------------------------------


@pytest.mark.parametrize("setup", [SetupMode.AUTO, SetupMode.NONE])
@pytest.mark.parametrize("parent", ["existing", "missing"])
def test_opening_and_reading_a_missing_database_creates_nothing(
    tmp_path: Path, setup: SetupMode, parent: str
) -> None:
    path = tmp_path / "envs.db" if parent == "existing" else tmp_path / "missing" / "envs.db"

    with open_sqlite(url_of(path), setup=setup) as adapter:
        assert adapter.list_stores() == []
        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")
        with pytest.raises(StoreNotFoundError):
            adapter.write_store(_next(_plain()), expected_revision=1)
        with pytest.raises(StoreNotFoundError):
            adapter.delete_store("base")

    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def deleted_after_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first existence check finds the file, but it is gone when SQLite opens it."""
    real = connection_module.is_missing
    checks: list[Path] = []

    def missing(path: Path) -> bool:
        checks.append(path)
        return False if len(checks) == 1 else real(path)

    monkeypatch.setattr(connection_module, "is_missing", missing)


@pytest.mark.usefixtures("umask_022", "deleted_after_check")
def test_a_read_on_a_file_deleted_mid_open_creates_nothing(path: Path) -> None:
    # Check-then-connect race: SQLite must not create the file itself (as 0644) on a read.
    with open_sqlite(url_of(path)) as adapter:
        assert adapter.list_stores() == []
        assert not path.exists()

        adapter.create_store(_plain())

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_path_with_uri_special_characters_names_the_same_file(tmp_path: Path) -> None:
    # The file is opened through a file: URI; spaces and percent signs must not be decoded.
    path = tmp_path / "dir %20" / "a b%41.db"

    with open_sqlite(url_of(path)) as writer:
        writer.create_store(_plain())
    with open_sqlite(url_of(path)) as reader:
        assert reader.read_store("base") == _plain()

    assert sorted(p.name for p in path.parent.iterdir() if p.suffix == ".db") == ["a b%41.db"]


def test_a_directory_in_place_of_the_database_raises_backend_error(path: Path) -> None:
    path.mkdir()

    with pytest.raises(BackendError, match="unable to open"), open_sqlite(url_of(path)) as adapter:
        adapter.list_stores()


def test_a_write_on_a_directory_in_place_of_the_database_raises_backend_error(
    path: Path,
) -> None:
    path.mkdir()

    with (
        pytest.raises(BackendError, match="unable to open"),
        open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter,
    ):
        adapter.create_store(_plain())


@pytest.mark.usefixtures("umask_022")
def test_first_write_creates_missing_directories_with_mode_0700(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "envs.db"

    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())

    modes = [stat.S_IMODE(directory.stat().st_mode) for directory in (path.parents[1], path.parent)]
    assert modes == [0o700, 0o700]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.usefixtures("umask_022")
def test_an_existing_parent_directory_keeps_its_mode(tmp_path: Path) -> None:
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o755)

    with open_sqlite(url_of(parent / "envs.db")) as adapter:
        adapter.create_store(_plain())

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755


@pytest.mark.usefixtures("umask_022")
def test_wal_and_shm_files_are_readable_by_the_owner_only(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        companions = [path.with_name(f"{path.name}{suffix}") for suffix in ("-wal", "-shm")]

        modes = [stat.S_IMODE(companion.stat().st_mode) for companion in companions]

    assert modes == [0o600, 0o600]


def test_migrate_creates_a_missing_directory_and_database(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "envs.db"

    with open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter:
        adapter.migrate()

    assert path.is_file()


def test_tilde_database_is_created_in_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    with open_sqlite("sqlite:///~/envs/envs.db") as adapter:
        adapter.create_store(_plain())

    assert (tmp_path / "envs" / "envs.db").is_file()


def test_a_database_created_after_open_is_used(path: Path) -> None:
    with open_sqlite(url_of(path)) as reader:
        assert reader.list_stores() == []
        with open_sqlite(url_of(path)) as writer:
            writer.create_store(_plain())

        assert reader.read_store("base") == _plain()


def test_operations_after_close_on_a_missing_database_raise_backend_error(path: Path) -> None:
    adapter = open_sqlite(url_of(path))
    adapter.close()

    with pytest.raises(BackendError, match="closed"):
        adapter.list_stores()


def test_deleted_values_do_not_stay_in_the_file(path: Path) -> None:
    marker = "deleted-secret-value-7f3a"
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(
            StoreRecord.plain(name="gone", variables={"PW": marker}, created_at=_T0)
        )
        adapter.delete_store("gone")

    assert marker.encode() not in path.read_bytes()


def test_a_missing_store_names_the_database_file(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter, pytest.raises(StoreNotFoundError) as raised:
        adapter.read_store("nope")

    assert str(raised.value) == f"store 'nope' not found in {path}"


# --- schema constraints --------------------------------------------------------------------


@pytest.mark.parametrize("row", [_VALID_PLAIN, _VALID_SEALED], ids=["plaintext", "encrypted"])
def test_check_constraints_accept_valid_rows(set_up_path: Path, row: tuple[object, ...]) -> None:
    with raw(set_up_path) as connection:
        connection.execute(_INSERT, row)


@pytest.mark.parametrize("row", _INVALID_ROWS.values(), ids=_INVALID_ROWS.keys())
def test_check_constraints_reject_invalid_rows(set_up_path: Path, row: tuple[object, ...]) -> None:
    with open_sqlite(url_of(set_up_path)) as adapter:
        with raw(set_up_path) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(_INSERT, row)

        assert adapter.list_stores() == []


def test_store_name_is_unique(set_up_path: Path) -> None:
    with raw(set_up_path) as connection:
        connection.execute(_INSERT, _VALID_PLAIN)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_INSERT, _VALID_PLAIN)


def test_write_breaking_a_constraint_raises_backend_error_and_writes_nothing(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        with raw(path) as connection:
            # Simulates a schema whose constraint rejects what the adapter writes.
            connection.execute(
                "CREATE TRIGGER no_updates BEFORE UPDATE ON stores "
                "BEGIN SELECT RAISE(ABORT, 'updates are blocked'); END"
            )
        record = StoreRecord.plain(name="base", variables={}, created_at=_T0, revision=2)

        with pytest.raises(BackendError, match="updates are blocked") as raised:
            adapter.write_store(record, expected_revision=1)

        assert isinstance(raised.value.__cause__, sqlite3.Error)
        assert adapter.read_store("base") == _plain()


# --- untrusted rows ------------------------------------------------------------------------


def test_corrupt_row_raises_backend_error_without_the_value(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        with raw(path) as connection:
            connection.execute("UPDATE stores SET variables = '{\"HOST\": s3cr3t'")

        with pytest.raises(BackendError, match="variables is not valid JSON") as raised:
            adapter.read_store("base")

    assert "s3cr3t" not in str(raised.value)


def test_unknown_cipher_is_listed_without_key_mode_but_not_readable(path: Path) -> None:
    sealed = StoreRecord.sealed(
        name="secret",
        ciphertext=b"\x00",
        cipher_meta=CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE),
        created_at=_T0,
    )
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(sealed)
        with raw(path) as connection:
            connection.execute('UPDATE stores SET cipher_meta = \'{"cipher":"rot13"}\'')

        (info,) = adapter.list_stores()
        assert info.encrypted
        assert info.key_mode is None
        with pytest.raises(UnsupportedFormatError):
            adapter.read_store("secret")


def test_dropped_stores_table_raises_backend_error(set_up_path: Path) -> None:
    with open_sqlite(url_of(set_up_path)) as adapter:
        with raw(set_up_path) as connection:
            connection.execute("DROP TABLE stores")

        with pytest.raises(BackendError, match="no such table"):
            adapter.list_stores()


# --- threads -------------------------------------------------------------------------------


def test_one_instance_can_be_shared_by_threads(path: Path) -> None:
    names = [f"store-{index}" for index in range(16)]

    with open_sqlite(url_of(path)) as adapter, ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda name: adapter.create_store(_plain(name)), names))

        assert [info.name for info in adapter.list_stores()] == sorted(names)


# --- transactions --------------------------------------------------------------------------


def test_transaction_commits_on_success(path: Path) -> None:
    with raw(path) as connection:
        with transaction(connection, immediate=True):
            connection.execute("CREATE TABLE t (x INTEGER)")

        assert not connection.in_transaction
        assert connection.execute("SELECT count(*) FROM t").fetchone() == (0,)


def _fail_in_transaction(connection: sqlite3.Connection, statement: str) -> None:
    with transaction(connection, immediate=True):
        connection.execute(statement)
        message = "boom"
        raise RuntimeError(message)


def test_transaction_rolls_back_on_error(path: Path) -> None:
    with raw(path) as connection:
        with pytest.raises(RuntimeError, match="boom"):
            _fail_in_transaction(connection, "CREATE TABLE t (x INTEGER)")

        assert not connection.in_transaction
        assert connection.execute("SELECT count(*) FROM sqlite_schema").fetchone() == (0,)


def test_transaction_keeps_the_error_when_sqlite_already_rolled_back(path: Path) -> None:
    with raw(path) as connection:
        # SQLite ends the transaction itself on some errors (e.g. a full disk).
        with pytest.raises(RuntimeError, match="boom"):
            _fail_in_transaction(connection, "ROLLBACK")

        assert not connection.in_transaction


_STORED_VALUE: Final = "hunter2-TOP-SECRET"


@pytest.mark.parametrize(
    ("stored", "error"),
    [
        (b'{"DB_PASSWORD":"hunter2-TOP-SECRET"}\xff', "variables is not valid JSON"),
        (b'{"DB_PASSWORD":"hunter2-TOP-SECRET\xff"}', "'DB_PASSWORD' is not valid UTF-8"),
    ],
    ids=["after-the-document", "inside-a-value"],
)
def test_invalid_utf8_in_a_row_raises_backend_error_without_the_value(
    path: Path, stored: bytes, error: str
) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(
            StoreRecord.plain(name="s", variables={"DB_PASSWORD": _STORED_VALUE}, created_at=_T0)
        )
        with raw(path) as connection:
            connection.execute("UPDATE stores SET variables = CAST(? AS TEXT)", (stored,))

        with pytest.raises(BackendError, match=error) as raised:
            adapter.read_store("s")

    assert "hunter2" not in "".join(traceback.format_exception(raised.value))


# --- revisions -----------------------------------------------------------------------------


def _at_revision(revision: int) -> StoreRecord:
    return StoreRecord.plain(
        name="base", variables={"HOST": "localhost"}, created_at=_T0, revision=revision
    )


def test_write_up_to_the_largest_revision_is_stored_as_an_integer(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        with raw(path) as connection:
            connection.execute("UPDATE stores SET revision = ?", (MAX_REVISION - 1,))

        adapter.write_store(_at_revision(MAX_REVISION), expected_revision=MAX_REVISION - 1)

        assert adapter.read_store("base").revision == MAX_REVISION


# --- failed commit -------------------------------------------------------------------------


def test_transaction_rolls_back_when_the_commit_fails(path: Path) -> None:
    with raw(path) as setup:
        setup.execute("CREATE TABLE t (x INTEGER)")
    # A rollback journal (no WAL): a reader's SHARED lock makes COMMIT fail with SQLITE_BUSY.
    writer = sqlite3.connect(path, autocommit=True, timeout=0.05)
    try:
        with raw(path) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT count(*) FROM t").fetchone()
            with pytest.raises(sqlite3.OperationalError, match="locked"):  # noqa: SIM117
                with transaction(writer, immediate=True):
                    writer.execute("INSERT INTO t VALUES (1)")

            assert not writer.in_transaction
            reader.execute("COMMIT")

        with transaction(writer, immediate=True):
            writer.execute("INSERT INTO t VALUES (2)")
        assert writer.execute("SELECT x FROM t").fetchall() == [(2,)]
    finally:
        writer.close()
