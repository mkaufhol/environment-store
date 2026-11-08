import sqlite3
from collections.abc import Iterator, Sequence

import pytest
from psycopg import sql

from environment_store.adapters.sql.migrations import (
    POSTGRES_MIGRATIONS,
    POSTGRES_SET_SCHEMA_VERSION,
    SQLITE_MIGRATIONS,
    SQLITE_SET_SCHEMA_VERSION,
    Migration,
    pending,
)
from environment_store.adapters.sql.schema import (
    POSTGRES_SCHEMA_V1,
    SCHEMA_VERSION,
    SQLITE_SCHEMA_V1,
)
from environment_store.core.errors import SchemaTooNewError, ValidationError

_V1 = Migration(version=1, statements=("CREATE TABLE a (x INTEGER)",))
_V2 = Migration(version=2, statements=("CREATE TABLE b (x INTEGER)",))
_V3 = Migration(version=3, statements=("CREATE TABLE c (x INTEGER)", "DROP TABLE b"))


@pytest.fixture
def connection() -> Iterator[sqlite3.Connection]:
    # autocommit=False: DDL runs inside the transaction as well (PEP 249 mode).
    database = sqlite3.connect(":memory:", autocommit=False)
    try:
        yield database
    finally:
        database.close()


def _apply(database: sqlite3.Connection, migrations: Sequence[Migration]) -> None:
    # What the SQLite adapter does: statements, then the version update, in one transaction.
    with database:
        for migration in migrations:
            for statement in migration.statements:
                database.execute(statement)
            database.execute(SQLITE_SET_SCHEMA_VERSION, (str(migration.version),))


def _stored_version(database: sqlite3.Connection) -> str:
    (value,) = database.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return value


# --- Migration ---------------------------------------------------------------------------------


def test_migration_keeps_version_and_statements() -> None:
    assert (_V3.version, _V3.statements) == (3, ("CREATE TABLE c (x INTEGER)", "DROP TABLE b"))


def test_migration_copies_statements_into_a_tuple() -> None:
    statements = ["CREATE TABLE a (x INTEGER)"]

    migration = Migration(version=1, statements=statements)  # ty: ignore[invalid-argument-type] - a list on purpose
    statements.append("DROP TABLE a")

    assert migration.statements == ("CREATE TABLE a (x INTEGER)",)


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1"])
def test_migration_rejects_a_version_that_is_not_a_positive_integer(version: object) -> None:
    with pytest.raises(ValidationError, match="version"):
        Migration(version=version, statements=("SELECT 1",))  # ty: ignore[invalid-argument-type] - invalid on purpose


@pytest.mark.parametrize(
    "statements",
    [(), ("",), ("  ",), ("SELECT 1", 2), "SELECT 1", None],
    ids=["empty", "blank", "whitespace", "non-string", "bare-string", "none"],
)
def test_migration_rejects_missing_or_invalid_statements(statements: object) -> None:
    with pytest.raises(ValidationError, match="statements"):
        Migration(version=1, statements=statements)  # ty: ignore[invalid-argument-type] - invalid on purpose


# --- pending -----------------------------------------------------------------------------------


def test_pending_on_an_empty_database_returns_every_migration() -> None:
    assert pending((_V1, _V2, _V3), None) == [_V1, _V2, _V3]


@pytest.mark.parametrize(
    ("current", "expected"),
    [(1, [_V2, _V3]), (2, [_V3]), (3, [])],
)
def test_pending_returns_the_migrations_after_the_current_version(
    current: int, expected: list[Migration]
) -> None:
    assert pending((_V1, _V2, _V3), current) == expected


def test_pending_sorts_the_migrations_by_version() -> None:
    assert pending((_V3, _V1, _V2), 1) == [_V2, _V3]


def test_pending_refuses_a_version_newer_than_the_last_migration() -> None:
    with pytest.raises(SchemaTooNewError, match="upgrade environment-store"):
        pending((_V1, _V2), 3)


@pytest.mark.parametrize("current", [0, -1, True, "1"])
def test_pending_rejects_a_current_version_that_is_not_a_positive_integer(
    current: object,
) -> None:
    with pytest.raises(ValidationError, match="current"):
        pending((_V1,), current)  # ty: ignore[invalid-argument-type] - invalid on purpose


@pytest.mark.parametrize(
    "migrations",
    [(), (_V2,), (_V1, _V3), (_V1, _V1)],
    ids=["none", "not-starting-at-1", "gap", "duplicate"],
)
def test_pending_rejects_migrations_that_are_not_numbered_1_to_n(
    migrations: tuple[Migration, ...],
) -> None:
    with pytest.raises(ValidationError, match="migrations"):
        pending(migrations, None)


# --- shipped migrations ------------------------------------------------------------------------


@pytest.mark.parametrize("migrations", [SQLITE_MIGRATIONS, POSTGRES_MIGRATIONS])
def test_shipped_migrations_end_at_the_schema_version(
    migrations: tuple[Migration, ...],
) -> None:
    assert [migration.version for migration in migrations] == list(range(1, SCHEMA_VERSION + 1))


def test_first_migration_creates_schema_v1() -> None:
    assert SQLITE_MIGRATIONS[0].statements == SQLITE_SCHEMA_V1
    assert POSTGRES_MIGRATIONS[0].statements == POSTGRES_SCHEMA_V1


def test_sqlite_migrations_create_a_current_database(connection: sqlite3.Connection) -> None:
    _apply(connection, pending(SQLITE_MIGRATIONS, None))

    assert _stored_version(connection) == str(SCHEMA_VERSION)


def test_sqlite_set_schema_version_updates_meta_after_an_upgrade(
    connection: sqlite3.Connection,
) -> None:
    upgrade = Migration(version=SCHEMA_VERSION + 1, statements=("CREATE TABLE extra (x INTEGER)",))
    migrations = (*SQLITE_MIGRATIONS, upgrade)
    _apply(connection, pending(migrations, None)[:-1])

    _apply(connection, pending(migrations, SCHEMA_VERSION))

    assert _stored_version(connection) == str(SCHEMA_VERSION + 1)


def test_sqlite_upgrade_failure_rolls_back_statements_and_version(
    connection: sqlite3.Connection,
) -> None:
    _apply(connection, SQLITE_MIGRATIONS)
    broken = Migration(
        version=SCHEMA_VERSION + 1,
        statements=("CREATE TABLE extra (x INTEGER)", "NOT VALID SQL"),
    )

    with pytest.raises(sqlite3.OperationalError):
        _apply(connection, [broken])

    assert _stored_version(connection) == str(SCHEMA_VERSION)
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = 'extra'"
    ).fetchone() == (0,)


def test_postgres_set_schema_version_composes_with_a_parameter() -> None:
    composed = (
        sql.SQL(POSTGRES_SET_SCHEMA_VERSION).format(schema=sql.Identifier("team_a")).as_string(None)
    )

    assert composed == ("UPDATE \"team_a\".meta SET value = %s WHERE key = 'schema_version'")
