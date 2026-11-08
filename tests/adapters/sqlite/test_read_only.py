"""`SetupMode.READ_ONLY` on SQLite: reads what is there and never writes a byte."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.sql.migrations import SQLITE_MIGRATIONS, Migration
from environment_store.adapters.sqlite import SqliteAdapter, open_sqlite
from environment_store.core.adapter import SetupMode
from environment_store.core.errors import (
    BackendError,
    DatabaseNotCleanError,
    SchemaOutdatedError,
    SchemaTooNewError,
    StoreNotFoundError,
)
from environment_store.core.models import StoreRecord
from tests.adapters.sqlite.backend import raw, url_of

_RO: Final = SetupMode.READ_ONLY
_V2: Final[Migration] = Migration(version=2, statements=("CREATE TABLE extra (x INTEGER)",))


def _record(name: str = "base") -> StoreRecord:
    return StoreRecord.plain(
        name=name, variables={"HOST": "localhost"}, created_at=datetime(2026, 11, 6, tzinfo=UTC)
    )


def _state(directory: Path) -> dict[str, str]:
    """Every file of the directory with the hash of its bytes."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
    }


def _current(path: Path, *names: str) -> None:
    with open_sqlite(url_of(path)) as adapter:
        for name in names:
            adapter.create_store(_record(name))


@pytest.mark.parametrize("parent", ["existing", "missing"])
def test_read_only_on_a_missing_file_finds_no_stores_and_creates_nothing(
    tmp_path: Path, parent: str
) -> None:
    path = tmp_path / "envs.db" if parent == "existing" else tmp_path / "missing" / "envs.db"

    with open_sqlite(url_of(path), setup=_RO) as adapter:
        assert adapter.list_stores() == []
        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")

    assert list(tmp_path.iterdir()) == []


def test_read_only_on_an_empty_file_finds_no_stores_and_leaves_it_byte_identical(
    tmp_path: Path,
) -> None:
    path = tmp_path / "envs.db"
    path.touch()

    with open_sqlite(url_of(path), setup=_RO) as adapter:
        assert adapter.list_stores() == []
        assert adapter.list_stores() == []
        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")

    assert _state(tmp_path) == {"envs.db": hashlib.sha256(b"").hexdigest()}


def test_read_only_reads_a_closed_wal_database_without_creating_journal_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / "envs.db"
    _current(path, "a", "b")
    before = _state(tmp_path)

    with open_sqlite(url_of(path), setup=_RO) as adapter:
        assert [info.name for info in adapter.list_stores()] == ["a", "b"]
        assert adapter.read_store("a") == _record("a")

    assert _state(tmp_path) == before


def test_read_only_sees_what_an_open_writer_committed(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    _current(path, "a")

    with open_sqlite(url_of(path)) as writer:
        writer.create_store(_record("b"))
        files = sorted(entry.name for entry in tmp_path.iterdir())
        with open_sqlite(url_of(path), setup=_RO) as reader:
            assert [info.name for info in reader.list_stores()] == ["a", "b"]
        assert sorted(entry.name for entry in tmp_path.iterdir()) == files


def test_read_only_refuses_migrate_and_leaves_an_empty_file_alone(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    path.touch()

    with (
        open_sqlite(url_of(path), setup=_RO) as adapter,
        pytest.raises(BackendError, match="read-only"),
    ):
        adapter.migrate()

    assert path.read_bytes() == b""


def test_read_only_refuses_an_outdated_schema_instead_of_upgrading_it(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    _current(path, "a")
    before = _state(tmp_path)

    with (
        SqliteAdapter(path, setup=_RO, migrations=(*SQLITE_MIGRATIONS, _V2)) as adapter,
        pytest.raises(SchemaOutdatedError),
    ):
        adapter.list_stores()

    assert _state(tmp_path) == before


def test_read_only_refuses_a_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    with SqliteAdapter(path, migrations=(*SQLITE_MIGRATIONS, _V2)) as adapter:
        adapter.create_store(_record())

    with open_sqlite(url_of(path), setup=_RO) as adapter, pytest.raises(SchemaTooNewError):
        adapter.list_stores()


def test_read_only_refuses_a_foreign_file_and_leaves_it_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    with raw(path) as connection:
        connection.execute("CREATE TABLE users (id INTEGER)")
    before = _state(tmp_path)

    with open_sqlite(url_of(path), setup=_RO) as adapter, pytest.raises(DatabaseNotCleanError):
        adapter.read_store("base")

    assert _state(tmp_path) == before


def test_read_only_write_to_a_missing_file_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "envs.db"

    with (
        open_sqlite(url_of(path), setup=_RO) as adapter,
        pytest.raises(BackendError, match="read-only"),
    ):
        adapter.create_store(_record())

    assert list(tmp_path.iterdir()) == []


def test_read_only_on_a_rollback_journal_database_honours_the_writers_lock(
    tmp_path: Path,
) -> None:
    # Without WAL there is never a -wal file; an immutable read would ignore the writer's lock
    # and could read half-written pages, so the plain read-only mode is used.
    path = tmp_path / "envs.db"
    _current(path, "a")
    with raw(path) as writer:
        writer.execute("PRAGMA journal_mode = DELETE")
        writer.execute("BEGIN EXCLUSIVE")
        try:
            with (
                SqliteAdapter(path, setup=_RO, busy_timeout=0.05) as adapter,
                pytest.raises(BackendError),
            ):
                adapter.list_stores()
        finally:
            writer.execute("ROLLBACK")

    with open_sqlite(url_of(path), setup=_RO) as adapter:
        assert [info.name for info in adapter.list_stores()] == ["a"]
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["envs.db"]


def test_read_only_on_an_unreadable_file_raises_backend_error(tmp_path: Path) -> None:
    path = tmp_path / "envs.db"
    _current(path, "a")
    path.chmod(0)
    try:
        with pytest.raises(BackendError, match="Permission denied"):
            open_sqlite(url_of(path), setup=_RO)
    finally:
        path.chmod(0o600)
