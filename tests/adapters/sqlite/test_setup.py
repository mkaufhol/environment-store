"""First setup, upgrades and refusals of a SQLite file (spec §3.3.2, D11, D13)."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.sql.migrations import SQLITE_MIGRATIONS, Migration
from environment_store.adapters.sqlite import SqliteAdapter, open_sqlite
from environment_store.core.adapter import MigrationReport, SetupMode
from environment_store.core.errors import (
    BackendError,
    DatabaseNotCleanError,
    SchemaTooNewError,
    ValidationError,
)
from environment_store.core.models import StoreRecord
from tests.adapters.sqlite.backend import meta_rows, raw, snapshot, tables, url_of

_V2: Final[Migration] = Migration(version=2, statements=("CREATE TABLE extra (x INTEGER)",))
_TWO_VERSIONS: Final[tuple[Migration, ...]] = (*SQLITE_MIGRATIONS, _V2)
_BROKEN_V2: Final[Migration] = Migration(
    version=2, statements=("CREATE TABLE extra (x INTEGER)", "THIS IS NOT SQL")
)
_RACERS: Final[int] = 8
_TIMEOUT: Final[float] = 30.0

# Files that are not empty and not ours: each must be refused without any change.
_FOREIGN: Final[dict[str, tuple[str, ...]]] = {
    "foreign table": ("CREATE TABLE users (id INTEGER)",),
    "foreign view": ("CREATE VIEW answer AS SELECT 42",),
    "meta of another app": (
        "CREATE TABLE meta (key TEXT, value TEXT)",
        "INSERT INTO meta VALUES ('app', 'other-tool'), ('schema_version', '1')",
    ),
    "meta without app": (
        "CREATE TABLE meta (key TEXT, value TEXT)",
        "INSERT INTO meta VALUES ('schema_version', '1')",
    ),
    "meta with a non-integer version": (
        "CREATE TABLE meta (key TEXT, value TEXT)",
        "INSERT INTO meta VALUES ('app', 'environment-store'), ('schema_version', 'one')",
    ),
    # Columns without a type keep the integer (a TEXT column would convert it to '1').
    "meta with a version stored as a number": (
        "CREATE TABLE meta (key, value)",
        "INSERT INTO meta VALUES ('app', 'environment-store'), ('schema_version', 1)",
    ),
    "meta with other columns": ("CREATE TABLE meta (id INTEGER, data BLOB)",),
    "our meta next to foreign tables but no version": (
        "CREATE TABLE meta (key TEXT, value TEXT)",
        "INSERT INTO meta VALUES ('app', 'environment-store')",
        "CREATE TABLE stores (id INTEGER)",
    ),
}


def _record(name: str = "base") -> StoreRecord:
    return StoreRecord.plain(
        name=name, variables={"HOST": "localhost"}, created_at=datetime(2026, 11, 6, tzinfo=UTC)
    )


def _execute(path: Path, statements: tuple[str, ...]) -> None:
    with raw(path) as connection:
        for statement in statements:
            connection.execute(statement)


def _db(tmp_path: Path) -> Path:
    return tmp_path / "envs.db"


# --- EMPTY ---------------------------------------------------------------------------------


def test_new_file_is_created_with_schema_v1_on_the_first_write(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    assert tables(path) == {"meta", "stores"}
    assert meta_rows(path) == {"app": "environment-store", "schema_version": "1"}


def test_existing_file_without_tables_is_set_up(tmp_path: Path) -> None:
    path = _db(tmp_path)
    path.touch()

    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    assert meta_rows(path)["schema_version"] == "1"


def test_database_uses_wal_journal_mode(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())
        mode, _ = snapshot(path)

    assert mode == "wal"


def test_parent_that_is_a_file_raises_backend_error(tmp_path: Path) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("", encoding="utf-8")

    with pytest.raises(BackendError, match="not-a-directory"):
        open_sqlite(url_of(occupied / "envs.db"))


def test_directory_that_cannot_be_created_raises_backend_error_on_the_first_write(
    tmp_path: Path,
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with (
            open_sqlite(url_of(locked / "new" / "envs.db")) as adapter,
            pytest.raises(BackendError, match="locked"),
        ):
            adapter.create_store(_record())
    finally:
        locked.chmod(0o700)


# --- CURRENT -------------------------------------------------------------------------------


def test_current_schema_is_used_and_keeps_its_stores(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    with open_sqlite(url_of(path)) as reopened:
        assert reopened.read_store("base") == _record()

    assert meta_rows(path) == {"app": "environment-store", "schema_version": "1"}


# --- OUTDATED ------------------------------------------------------------------------------


def test_outdated_schema_is_upgraded_automatically_and_keeps_its_stores(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    with SqliteAdapter(path, migrations=_TWO_VERSIONS) as upgraded:
        assert upgraded.read_store("base") == _record()

    assert meta_rows(path)["schema_version"] == "2"
    assert "extra" in tables(path)


def test_failing_upgrade_is_rolled_back_completely(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    with pytest.raises(BackendError, match="syntax error"):
        SqliteAdapter(path, migrations=(*SQLITE_MIGRATIONS, _BROKEN_V2))

    assert meta_rows(path)["schema_version"] == "1"
    assert "extra" not in tables(path)
    with open_sqlite(url_of(path)) as reopened:
        assert reopened.read_store("base") == _record()


def test_failing_first_setup_creates_no_tables(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with (
        SqliteAdapter(path, migrations=(*SQLITE_MIGRATIONS, _BROKEN_V2)) as adapter,
        pytest.raises(BackendError),
    ):
        adapter.migrate()

    assert tables(path) == set()


# --- NEWER and FOREIGN ---------------------------------------------------------------------


def test_newer_schema_is_refused_and_left_unchanged(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with SqliteAdapter(path, migrations=_TWO_VERSIONS) as adapter:
        adapter.create_store(_record())
    before = snapshot(path)

    with pytest.raises(SchemaTooNewError, match="upgrade environment-store"):
        open_sqlite(url_of(path))

    assert snapshot(path) == before


@pytest.mark.parametrize("statements", _FOREIGN.values(), ids=_FOREIGN.keys())
def test_foreign_file_is_refused_and_left_unchanged(
    tmp_path: Path, statements: tuple[str, ...]
) -> None:
    path = _db(tmp_path)
    _execute(path, statements)
    before = snapshot(path)

    with pytest.raises(DatabaseNotCleanError, match=r"not an environment-store database"):
        open_sqlite(url_of(path))

    # Not even the journal mode was switched to WAL.
    assert snapshot(path) == before


def test_refusal_message_names_the_file(tmp_path: Path) -> None:
    path = _db(tmp_path)
    _execute(path, _FOREIGN["foreign table"])

    with pytest.raises(DatabaseNotCleanError) as raised:
        open_sqlite(url_of(path))

    assert str(path) in str(raised.value)


def test_file_that_is_not_a_database_raises_backend_error_and_is_kept(tmp_path: Path) -> None:
    path = _db(tmp_path)
    path.write_text("just some text, long enough to be read as a database header\n" * 4)
    before = path.read_bytes()

    with pytest.raises(BackendError, match="not a database"):
        open_sqlite(url_of(path))

    assert path.read_bytes() == before


# --- SetupMode.NONE and migrate() ----------------------------------------------------------


def test_setup_none_does_not_touch_the_file_on_open(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with open_sqlite(url_of(path), setup=SetupMode.NONE):
        assert tables(path) == set()


def test_setup_none_runs_the_setup_on_the_first_data_operation(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter:
        adapter.create_store(_record())

        assert meta_rows(path)["schema_version"] == "1"
        assert adapter.read_store("base") == _record()


def test_setup_none_opens_a_foreign_file_but_refuses_data_operations(tmp_path: Path) -> None:
    path = _db(tmp_path)
    _execute(path, _FOREIGN["foreign table"])
    before = snapshot(path)

    with open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter:
        with pytest.raises(DatabaseNotCleanError):
            adapter.list_stores()
        with pytest.raises(DatabaseNotCleanError):
            adapter.migrate()

    assert snapshot(path) == before


def test_migrate_creates_the_schema_in_a_new_file(tmp_path: Path) -> None:
    path = _db(tmp_path)

    with open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter:
        report = adapter.migrate()

    assert report == MigrationReport(from_version=None, to_version=1, created=True)
    assert meta_rows(path)["schema_version"] == "1"


@pytest.mark.parametrize("setup", list(SetupMode))
def test_migrate_is_a_no_op_on_a_current_schema(tmp_path: Path, setup: SetupMode) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())
    before = snapshot(path)

    with open_sqlite(url_of(path), setup=setup) as adapter:
        report = adapter.migrate()

    assert report == MigrationReport(from_version=1, to_version=1, created=False)
    assert snapshot(path) == before


def test_migrate_upgrades_an_outdated_schema(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    with SqliteAdapter(path, setup=SetupMode.NONE, migrations=_TWO_VERSIONS) as upgraded:
        report = upgraded.migrate()
        assert upgraded.read_store("base") == _record()

    assert report == MigrationReport(from_version=1, to_version=2, created=False)
    assert meta_rows(path)["schema_version"] == "2"


def test_migrate_refuses_a_newer_schema(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with SqliteAdapter(path, migrations=_TWO_VERSIONS) as newer:
        newer.migrate()

    with (
        open_sqlite(url_of(path), setup=SetupMode.NONE) as adapter,
        pytest.raises(SchemaTooNewError),
    ):
        adapter.migrate()

    assert meta_rows(path)["schema_version"] == "2"


def test_migrate_after_close_raises_backend_error(tmp_path: Path) -> None:
    adapter = open_sqlite(url_of(_db(tmp_path)), setup=SetupMode.NONE)
    adapter.close()

    with pytest.raises(BackendError, match="closed"):
        adapter.migrate()


@pytest.mark.parametrize(
    "migrations",
    [(), (_V2,), (*SQLITE_MIGRATIONS, _V2, _V2)],
    ids=["none", "gap", "duplicate"],
)
def test_migrations_not_numbered_one_to_n_are_rejected(
    tmp_path: Path, migrations: tuple[Migration, ...]
) -> None:
    path = _db(tmp_path)

    with pytest.raises(ValidationError):
        SqliteAdapter(path, migrations=migrations)

    assert not path.exists()


# --- concurrent opens ----------------------------------------------------------------------


def _open_in_parallel(path: Path) -> list[BaseException | None]:
    barrier = threading.Barrier(_RACERS, timeout=_TIMEOUT)

    def run(index: int) -> BaseException | None:
        barrier.wait()
        try:
            # A write: on a missing file it is the first one, which creates file and schema.
            with open_sqlite(url_of(path)) as adapter:
                adapter.create_store(_record(f"racer-{index}"))
        except BackendError as err:
            return err
        return None

    with ThreadPoolExecutor(max_workers=_RACERS) as pool:
        futures = [pool.submit(run, index) for index in range(_RACERS)]
        return [future.result(timeout=_TIMEOUT) for future in futures]


def test_racing_first_writes_to_a_new_file_all_succeed_and_set_up_once(tmp_path: Path) -> None:
    path = _db(tmp_path)

    assert _open_in_parallel(path) == [None] * _RACERS

    with raw(path) as connection:
        assert connection.execute("SELECT count(*) FROM meta").fetchone() == (2,)
    assert meta_rows(path)["schema_version"] == "1"


def test_racing_opens_of_a_set_up_file_all_succeed(tmp_path: Path) -> None:
    path = _db(tmp_path)
    with open_sqlite(url_of(path)) as adapter:
        adapter.create_store(_record())

    assert _open_in_parallel(path) == [None] * _RACERS


# --- locks ---------------------------------------------------------------------------------


def _hold_write_lock(path: Path) -> sqlite3.Connection:
    # A writer that holds the RESERVED lock: switching to WAL fails at once (SQLite does not
    # wait, to avoid a deadlock), unlike ordinary lock waits that the busy timeout covers.
    holder = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    return holder


def test_switch_to_wal_retries_while_another_connection_holds_the_write_lock(
    tmp_path: Path,
) -> None:
    path = _db(tmp_path)
    holder = _hold_write_lock(path)
    release = threading.Timer(0.2, holder.execute, args=("COMMIT",))
    release.start()
    try:
        with SqliteAdapter(path, busy_timeout=_TIMEOUT) as adapter:
            adapter.create_store(_record())
    finally:
        release.join()
        holder.close()

    assert snapshot(path)[0] == "wal"


def test_lock_held_longer_than_the_busy_timeout_raises_backend_error(tmp_path: Path) -> None:
    path = _db(tmp_path)
    holder = _hold_write_lock(path)
    try:
        with pytest.raises(BackendError, match="locked"):
            SqliteAdapter(path, busy_timeout=0.1)
    finally:
        holder.close()

    assert tables(path) == set()


def test_busy_timeout_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="busy timeout"):
        SqliteAdapter(_db(tmp_path), busy_timeout=0)
