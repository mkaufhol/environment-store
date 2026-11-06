"""First setup and migrations of a SQLite database file (D11, D13).

The adapter inspects the file (its tables and the `meta` rows), the shared pure setup logic
classifies it and decides, and `set_up` applies the pending migrations in one write transaction.
SQLite upgrades automatically (D11). A refused file (foreign content or a newer schema) is never
written to: the decision is made before the journal mode is changed or a write lock is taken.
"""

import sqlite3
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Final

from environment_store.adapters.sql.migrations import SQLITE_SET_SCHEMA_VERSION, Migration, pending
from environment_store.adapters.sql.schema import META_TABLE
from environment_store.adapters.sql.setup import (
    DatabaseInspection,
    SetupState,
    classify,
    decide,
    stored_version,
)
from environment_store.core.adapter import MigrationReport

__all__ = ["inspect", "set_up", "transaction"]

# Every table and view except SQLite's own (`sqlite_sequence`, `sqlite_stat1`, ...). The
# backslash escapes `_`, which LIKE would otherwise treat as a wildcard.
_TABLES: Final = (
    "SELECT name FROM sqlite_schema "
    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
)
_META_ROWS: Final = "SELECT key, value FROM meta"
_WAL: Final = "wal"
_RETRY_PAUSE_SECONDS: Final[float] = 0.01


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool) -> Generator[None]:
    """Run a block in one explicit transaction; commit on success, roll back on any error.

    The connection must be in autocommit mode (`autocommit=True`), so the explicit `BEGIN`
    also covers DDL: a migration and its `schema_version` update are atomic.

    Args:
        connection: An autocommit connection without an open transaction.
        immediate: Take the write lock at `BEGIN`, so a read in the block cannot be invalidated
            by another writer before this transaction writes.

    Yields:
        Nothing; the block runs inside the transaction.
    """
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        # Some errors (e.g. a full disk) make SQLite roll back on its own.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def inspect(connection: sqlite3.Connection) -> DatabaseInspection:
    """Read what the database file contains, for `classify`.

    Args:
        connection: A connection; run this inside a transaction for one consistent snapshot.

    Returns:
        The tables and views (without SQLite's own) and the text rows of `meta`, if any.
    """
    tables = frozenset(name for (name,) in connection.execute(_TABLES).fetchall())
    if META_TABLE not in tables:
        return DatabaseInspection(tables=tables, meta=None)
    try:
        rows = connection.execute(_META_ROWS).fetchall()
    except sqlite3.OperationalError:
        # A foreign `meta` without our columns: no valid meta, so the file is foreign.
        return DatabaseInspection(tables=tables, meta=None)
    meta = {key: value for key, value in rows if isinstance(key, str) and isinstance(value, str)}
    return DatabaseInspection(tables=tables, meta=meta)


def set_up(
    connection: sqlite3.Connection,
    *,
    migrations: Sequence[Migration],
    location: str,
    busy_timeout: float,
) -> MigrationReport:
    """Create, upgrade or just check the schema of a database file (spec §3.3.2).

    Several connections may run this at the same time, also on a new file: the state is
    checked again under the write lock, so exactly one of them creates or upgrades the schema.

    Args:
        connection: An autocommit connection without an open transaction.
        migrations: Every migration of the dialect; the last one is this client's version.
        location: The file path, for error messages.
        busy_timeout: How long, in seconds, to keep retrying the switch to WAL mode while
            other connections hold locks.

    Returns:
        What was done; `from_version == to_version` when the schema was already current.

    Raises:
        DatabaseNotCleanError: The file holds foreign content; nothing was changed.
        SchemaTooNewError: The schema is newer than this client; nothing was changed.
    """
    client_version = len(migrations)
    with transaction(connection, immediate=False):
        inspection = inspect(connection)
    state = classify(inspection, client_version=client_version)
    if state is not SetupState.CURRENT:
        # Refuse before anything is written, not even the journal mode.
        decide(state, auto_upgrade=True, location=location)
    _use_wal(connection, timeout=busy_timeout)
    if state is not SetupState.CURRENT:
        with transaction(connection, immediate=True):
            # Another connection may have set the file up in the meantime.
            inspection = inspect(connection)
            decide(
                classify(inspection, client_version=client_version),
                auto_upgrade=True,
                location=location,
            )
            for migration in pending(migrations, stored_version(inspection)):
                _apply(connection, migration)
    found = stored_version(inspection)
    return MigrationReport(from_version=found, to_version=client_version, created=found is None)


def _use_wal(connection: sqlite3.Connection, *, timeout: float) -> None:
    # WAL lets readers and the writer work at the same time. The mode is stored in the file, so
    # only the first connection changes it. While another connection holds the write lock, SQLite
    # refuses the switch at once instead of waiting (deadlock avoidance), so retry until the
    # busy timeout is spent; several first opens of a new file race exactly here.
    deadline = time.monotonic() + timeout
    while True:
        (mode,) = connection.execute("PRAGMA journal_mode").fetchone()
        if mode == _WAL:
            return
        try:
            # A file system without WAL support keeps the old mode; that is not an error.
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as err:
            if err.sqlite_errorcode != sqlite3.SQLITE_BUSY or time.monotonic() >= deadline:
                raise
            time.sleep(_RETRY_PAUSE_SECONDS)
        else:
            return


def _apply(connection: sqlite3.Connection, migration: Migration) -> None:
    for statement in migration.statements:
        connection.execute(statement)
    connection.execute(SQLITE_SET_SCHEMA_VERSION, (str(migration.version),))
