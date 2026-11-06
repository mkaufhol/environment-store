"""The PostgreSQL adapter: one row per store in a dedicated schema (spec §3.3, D8, D10-D13).

One `psycopg` connection per adapter instance, in autocommit mode: every data operation is a
single atomic statement, and the first setup runs in one explicit transaction. Driver errors are
raised as `BackendError` naming the schema and database, never credentials or stored values.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from types import TracebackType
from typing import Final, Self

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from environment_store.adapters.postgres.schema import (
    apply_migrations,
    inspect_schema,
    lock_schema,
)
from environment_store.adapters.postgres.url import PostgresTarget, parse_url
from environment_store.adapters.sql.codec import (
    Dialect,
    StoreInfoRow,
    StoreRow,
    record_to_row,
    row_to_info,
    row_to_record,
)
from environment_store.adapters.sql.migrations import POSTGRES_MIGRATIONS, Migration, pending
from environment_store.adapters.sql.schema import STORE_INFO_COLUMNS, STORES_COLUMNS
from environment_store.adapters.sql.setup import (
    SetupAction,
    SetupState,
    classify,
    decide,
    stored_version,
)
from environment_store.core.adapter import MigrationReport, SetupMode, check_create, check_write
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    SetupPrivilegeError,
    StoreExistsError,
    StoreNotFoundError,
)
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.core.validation import validate_store_name

__all__ = ["PostgresAdapter", "open_postgres"]

_COLUMNS: Final = sql.SQL(", ").join(map(sql.Identifier, STORES_COLUMNS))
_INFO_COLUMNS: Final = sql.SQL(", ").join(map(sql.Identifier, STORE_INFO_COLUMNS))
_PLACEHOLDERS: Final = sql.SQL(", ").join(sql.Placeholder() for _ in STORES_COLUMNS)

# COLLATE "C" sorts UTF-8 by byte, which is code point order, whatever the database collation.
_LIST: Final = sql.SQL('SELECT {columns} FROM {schema}.stores ORDER BY name COLLATE "C"')
_READ: Final = sql.SQL("SELECT {columns} FROM {schema}.stores WHERE name = %s")
_CREATE: Final = sql.SQL(
    "INSERT INTO {schema}.stores ({columns}) VALUES ({values}) ON CONFLICT (name) DO NOTHING"
)
# The revision check and the replacement are one statement, so the check is atomic (D7).
_WRITE: Final = sql.SQL(
    "UPDATE {schema}.stores SET encrypted = %s, cipher_meta = %s, variables = %s, "
    "ciphertext = %s, revision = %s, created_at = %s, updated_at = %s "
    "WHERE name = %s AND revision = %s"
)
_REVISION: Final = sql.SQL("SELECT revision FROM {schema}.stores WHERE name = %s")
_DELETE: Final = sql.SQL("DELETE FROM {schema}.stores WHERE name = %s")


def open_postgres(url: str, *, setup: SetupMode = SetupMode.AUTO) -> "PostgresAdapter":
    """Open a PostgreSQL adapter; the factory registered for `postgresql://` and `postgres://`.

    Args:
        url: `postgresql://user@host/db?schema=<name>`; `schema` defaults to
            `environment_store` and is removed before the URL reaches the driver.
        setup: `AUTO` inspects and, if empty, creates the schema now; `NONE` only connects.

    Returns:
        The open adapter.

    Raises:
        ValidationError: Not a PostgreSQL URL or an invalid schema name.
        BackendError: The server cannot be reached, or the schema is refused (see
            `PostgresAdapter`).
    """
    return PostgresAdapter(parse_url(url), setup=setup)


class PostgresAdapter:
    """An `Adapter` (and `MigratableAdapter`) on one PostgreSQL schema.

    With `SetupMode.AUTO` the schema is inspected on open: missing or empty → created at the
    latest version in one transaction; ours and current → used; anything else is refused
    (outdated → run `migrate`, D11). With `SetupMode.NONE` the same check runs before the first
    data operation, and `migrate()` may create or upgrade the schema instead.
    """

    _target: PostgresTarget
    _migrations: tuple[Migration, ...]
    _connection: psycopg.Connection[TupleRow]
    _ready: bool
    _closed: bool

    def __init__(
        self,
        target: PostgresTarget,
        *,
        setup: SetupMode = SetupMode.AUTO,
        migrations: Sequence[Migration] = POSTGRES_MIGRATIONS,
    ) -> None:
        """Connect and, with `SetupMode.AUTO`, check or create the schema.

        Args:
            target: Where to connect, from `parse_url`.
            setup: How to treat the schema on open (D11, D13).
            migrations: All migrations this client knows; the last one is its schema version.

        Raises:
            ValidationError: The migrations are not numbered 1 to n.
            BackendError: The connection failed or the schema is refused; the connection is
                closed again.
        """
        self._target = target
        # pending(..., None) validates the numbering and returns all migrations in order.
        self._migrations = tuple(pending(migrations, None))
        self._ready = False
        self._closed = False
        self._connection = self._connect()
        if setup is SetupMode.AUTO:
            try:
                self._set_up(auto_upgrade=False)
            except BaseException:
                self._connection.close()
                raise

    def __repr__(self) -> str:
        """Name the location, never the connection string."""
        return f"PostgresAdapter({self._target.location})"

    # --- data operations -----------------------------------------------------------------

    def list_stores(self) -> list[StoreInfo]:
        """List every store, sorted by name in code point order.

        Returns:
            One entry per store.
        """
        with self._session("listing stores") as connection:
            rows = connection.execute(self._sql(_LIST, columns=_INFO_COLUMNS)).fetchall()
        return [row_to_info(_info_row(row), dialect=Dialect.POSTGRES) for row in rows]

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store; of two racing creates exactly one wins.

        Args:
            record: The new store at revision 1.

        Raises:
            StoreExistsError: A store with this name exists.
        """
        check_create(record)
        statement = self._sql(_CREATE, columns=_COLUMNS, values=_PLACEHOLDERS)
        with self._session(f"creating store {record.name!r}") as connection:
            created = connection.execute(statement, _parameters(record)).rowcount
        if created == 0:
            message = f"store {record.name!r} already exists in {self._target.location}"
            raise StoreExistsError(message)

    def read_store(self, name: str) -> StoreRecord:
        """Read a store.

        Args:
            name: The store name.

        Returns:
            The record as it was written.

        Raises:
            StoreNotFoundError: The store does not exist.
        """
        validate_store_name(name)
        with self._session(f"reading store {name!r}") as connection:
            row = connection.execute(self._sql(_READ, columns=_COLUMNS), (name,)).fetchone()
        if row is None:
            raise self._not_found(name)
        return row_to_record(_store_row(row), dialect=Dialect.POSTGRES)

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store if its stored revision is still `expected_revision` (D7).

        Args:
            record: The new content at `expected_revision + 1`.
            expected_revision: The revision that was read.

        Raises:
            StoreNotFoundError: The store does not exist.
            ConcurrentModificationError: The stored revision differs; nothing was written.
        """
        check_write(record, expected_revision=expected_revision)
        name, *values = _parameters(record)
        with self._session(f"writing store {record.name!r}") as connection:
            parameters = (*values, name, expected_revision)
            if connection.execute(self._sql(_WRITE), parameters).rowcount:
                return
            found = connection.execute(self._sql(_REVISION), (name,)).fetchone()
        if found is None:
            raise self._not_found(record.name)
        message = (
            f"store {record.name!r} was changed concurrently: it is at revision {found[0]}, "
            f"expected {expected_revision}; nothing was written"
        )
        raise ConcurrentModificationError(message)

    def delete_store(self, name: str) -> None:
        """Delete a store.

        Args:
            name: The store name.

        Raises:
            StoreNotFoundError: The store does not exist.
        """
        validate_store_name(name)
        with self._session(f"deleting store {name!r}") as connection:
            deleted = connection.execute(self._sql(_DELETE), (name,)).rowcount
        if deleted == 0:
            raise self._not_found(name)

    # --- schema --------------------------------------------------------------------------

    def migrate(self) -> MigrationReport:
        """Create (missing or empty schema) or upgrade (outdated schema); no-op when current.

        Returns:
            What was done.

        Raises:
            DatabaseNotCleanError: The schema holds foreign content.
            SchemaTooNewError: The schema is newer than this client.
            SetupPrivilegeError: The user lacks a privilege the migration needs.
        """
        self._check_open()
        return self._set_up(auto_upgrade=True)

    # --- lifecycle -----------------------------------------------------------------------

    def close(self) -> None:
        """Close the connection; idempotent."""
        self._closed = True
        self._connection.close()

    def __enter__(self) -> Self:
        """Return the adapter itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the adapter; never suppresses an exception."""
        self.close()

    # --- internals -----------------------------------------------------------------------

    def _connect(self) -> psycopg.Connection[TupleRow]:
        try:
            return psycopg.connect(self._target.conninfo, autocommit=True)
        except psycopg.Error as err:
            detail = self._target.redact(str(err).strip())
            message = f"cannot connect to PostgreSQL ({self._target.location}): {detail}"
            raise BackendError(message) from err

    def _set_up(self, *, auto_upgrade: bool) -> MigrationReport:
        """Inspect, decide and create or upgrade in one locked transaction (D11, D13)."""
        schema = self._target.schema
        client_version = self._migrations[-1].version
        try:
            with self._connection.transaction():
                lock_schema(self._connection, schema)
                inspection, exists = inspect_schema(self._connection, schema)
                state = classify(inspection, client_version=client_version)
                action = decide(state, auto_upgrade=auto_upgrade, location=self._target.location)
                found = stored_version(inspection)
                if action is not SetupAction.USE:
                    todo = pending(self._migrations, found)
                    apply_migrations(self._connection, schema, todo, create_schema=not exists)
        except psycopg.errors.InsufficientPrivilege as err:
            message = (
                f"the database user lacks a privilege needed to set up or use "
                f"{self._target.location} ({err.diag.message_primary}). An admin can run "
                "'environment-store migrate' once with a privileged user and grant this user "
                "USAGE on the schema and SELECT, INSERT, UPDATE, DELETE on its tables"
            )
            raise SetupPrivilegeError(message) from err
        except psycopg.Error as err:
            operation = "setting up the schema"
            raise self._driver_error(operation, err) from err
        self._ready = True
        created = state is SetupState.EMPTY
        return MigrationReport(
            from_version=None if created else found, to_version=client_version, created=created
        )

    @contextmanager
    def _session(self, operation: str) -> Generator[psycopg.Connection[TupleRow]]:
        self._check_open()
        if not self._ready:
            # SetupMode.NONE: the AUTO check runs lazily before the first data operation.
            self._set_up(auto_upgrade=False)
        try:
            yield self._connection
        except psycopg.Error as err:
            raise self._driver_error(operation, err) from err

    def _check_open(self) -> None:
        if self._closed:
            message = f"the PostgreSQL adapter for {self._target.location} is closed"
            raise BackendError(message)

    def _driver_error(self, operation: str, err: psycopg.Error) -> BackendError:
        # Only the primary message of a server error: DETAIL lines may quote stored values.
        if err.sqlstate is None:
            detail = self._target.redact(str(err).strip())
        else:
            detail = f"{err.diag.message_primary} (SQLSTATE {err.sqlstate})"
        message = f"PostgreSQL error while {operation} in {self._target.location}: {detail}"
        return BackendError(message)

    def _not_found(self, name: str) -> StoreNotFoundError:
        return StoreNotFoundError(f"store {name!r} not found in {self._target.location}")

    def _sql(self, template: sql.SQL, **parts: sql.Composable) -> sql.Composed:
        return template.format(schema=sql.Identifier(self._target.schema), **parts)


def _parameters(record: StoreRecord) -> tuple[object, ...]:
    """The `stores` column values of a record, in DDL order, ready for psycopg."""
    row = record_to_row(record, dialect=Dialect.POSTGRES)
    return (
        row.name,
        row.encrypted,
        None if row.cipher_meta is None else Jsonb(row.cipher_meta),
        None if row.variables is None else Jsonb(row.variables),
        row.ciphertext,
        row.revision,
        row.created_at,
        row.updated_at,
    )


def _utc(value: datetime) -> datetime:
    # TIMESTAMPTZ comes back in the session time zone; records are UTC.
    return value.astimezone(UTC)


def _store_row(row: TupleRow) -> StoreRow:
    # Driver values are untrusted; the codec validates every column.
    name, encrypted, cipher_meta, variables, ciphertext, revision, created, updated = row
    return StoreRow(
        name=name,
        encrypted=encrypted,
        cipher_meta=cipher_meta,
        variables=variables,
        ciphertext=ciphertext,
        revision=revision,
        created_at=_utc(created),
        updated_at=_utc(updated),
    )


def _info_row(row: TupleRow) -> StoreInfoRow:
    name, encrypted, cipher_meta, revision, created, updated = row
    return StoreInfoRow(
        name=name,
        encrypted=encrypted,
        cipher_meta=cipher_meta,
        revision=revision,
        created_at=_utc(created),
        updated_at=_utc(updated),
    )
