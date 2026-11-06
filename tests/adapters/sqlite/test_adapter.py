"""SQLite specifics beyond the contract: connection strings, constraints, corrupt rows, threads."""

import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.sqlite import SqliteAdapter, open_sqlite
from environment_store.adapters.sqlite.schema import transaction
from environment_store.core.adapter import Adapter, MigratableAdapter
from environment_store.core.connection import open_adapter
from environment_store.core.errors import BackendError, UnsupportedFormatError, ValidationError
from environment_store.core.models import Cipher, CipherMeta, KeyMode, StoreRecord
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

# Rows that break the D12 check constraints: never plaintext and encrypted at once, never
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


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "envs.db"


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


# --- schema constraints (D12) --------------------------------------------------------------


@pytest.mark.parametrize("row", [_VALID_PLAIN, _VALID_SEALED], ids=["plaintext", "encrypted"])
def test_check_constraints_accept_valid_rows(path: Path, row: tuple[object, ...]) -> None:
    with open_sqlite(url_of(path)), raw(path) as connection:
        connection.execute(_INSERT, row)


@pytest.mark.parametrize("row", _INVALID_ROWS.values(), ids=_INVALID_ROWS.keys())
def test_check_constraints_reject_invalid_rows(path: Path, row: tuple[object, ...]) -> None:
    with open_sqlite(url_of(path)) as adapter:
        with raw(path) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute(_INSERT, row)

        assert adapter.list_stores() == []


def test_store_name_is_unique(path: Path) -> None:
    with open_sqlite(url_of(path)), raw(path) as connection:
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


def test_dropped_stores_table_raises_backend_error(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        with raw(path) as connection:
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

_MAX_REVISION: Final = 2**63 - 1  # SQLite's largest INTEGER


def _at_revision(revision: int) -> StoreRecord:
    return StoreRecord.plain(
        name="base", variables={"HOST": "localhost"}, created_at=_T0, revision=revision
    )


@pytest.mark.parametrize("expected", [_MAX_REVISION, _MAX_REVISION + 1, 2**64])
def test_write_beyond_the_largest_revision_raises_validation_error(
    path: Path, expected: int
) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        with pytest.raises(ValidationError, match="revision"):
            adapter.write_store(_at_revision(expected + 1), expected_revision=expected)

        assert adapter.read_store("base") == _plain()


def test_write_up_to_the_largest_revision_is_stored_as_an_integer(path: Path) -> None:
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_plain())
        with raw(path) as connection:
            connection.execute("UPDATE stores SET revision = ?", (_MAX_REVISION - 1,))

        adapter.write_store(_at_revision(_MAX_REVISION), expected_revision=_MAX_REVISION - 1)

        assert adapter.read_store("base").revision == _MAX_REVISION


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
