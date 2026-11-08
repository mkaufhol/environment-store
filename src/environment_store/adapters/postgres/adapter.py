"""The PostgreSQL adapter: one row per store in a dedicated schema (spec §3.3, D8, D10-D13).

One `psycopg` connection per adapter instance, in autocommit mode: every data operation is a
single atomic statement, and the first setup runs in one explicit transaction. Driver errors are
raised as `BackendError` naming the schema and database, never credentials or stored values.
"""

from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Final, Self

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from environment_store.adapters.postgres import rows as table
from environment_store.adapters.postgres.schema import (
    apply_migrations,
    inspect_schema,
    lock_schema,
)
from environment_store.adapters.postgres.url import PostgresTarget, parse_url
from environment_store.adapters.sql.codec import Dialect, row_to_info, row_to_record
from environment_store.adapters.sql.migrations import POSTGRES_MIGRATIONS, Migration, pending
from environment_store.adapters.sql.setup import (
    SetupAction,
    SetupState,
    classify,
    decide,
    stored_version,
)
from environment_store.core.adapter import (
    MigrationReport,
    SetupMode,
    check_create,
    check_writable,
    check_write,
)
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    SetupPrivilegeError,
    StoreExistsError,
    StoreNotFoundError,
)
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.core.validation import validate_store_name

__all__ = ["READ_ONLY_CONNECT_TIMEOUT", "PostgresAdapter", "open_postgres"]

READ_ONLY_CONNECT_TIMEOUT: Final = 2
"""Seconds a `SetupMode.READ_ONLY` adapter waits for the server (D54); libpq's minimum."""

# TIMESTAMPTZ is sent in the session time zone: in local time, an instant near year 1 or 9999 UTC
# can fall in year 0 or 10000, which the driver cannot load. A plain SET persists after COMMIT.
_PIN_UTC: Final = sql.SQL("SET TIME ZONE 'UTC'")
# READ_ONLY: the server refuses any write of this session too (D54).
_READ_ONLY_SESSION: Final = sql.SQL("SET default_transaction_read_only = on")


def open_postgres(url: str, *, setup: SetupMode = SetupMode.AUTO) -> "PostgresAdapter":
    """Open a PostgreSQL adapter; the factory registered for `postgresql://` and `postgres://`.

    Args:
        url: `postgresql://user@host/db?schema=<name>`; `schema` defaults to
            `environment_store` and is removed before the URL reaches the driver.
        setup: `AUTO` inspects and, if empty, creates the schema now; `NONE` only connects;
            `READ_ONLY` connects with a short timeout and never sets anything up (D54).

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
    data operation, and `migrate()` may create or upgrade the schema instead. With
    `SetupMode.READ_ONLY` the session is read-only, a missing or empty schema holds no stores, any
    other schema than a current one is refused, and writes and `migrate()` raise (D54).
    """

    _target: PostgresTarget
    _setup: SetupMode
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
        self._setup = setup
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
        statement = self._sql(table.LIST, columns=table.INFO_COLUMNS)
        rows = self._read("listing stores", lambda c: c.execute(statement).fetchall(), empty=[])
        return [row_to_info(table.info_row(row), dialect=Dialect.POSTGRES) for row in rows]

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store; of two racing creates exactly one wins.

        Args:
            record: The new store at revision 1.

        Raises:
            StoreExistsError: A store with this name exists.
        """
        check_create(record)
        check_writable(self._setup, location=self._target.location)
        statement = self._sql(table.CREATE, columns=table.COLUMNS, values=table.PLACEHOLDERS)
        parameters = table.record_parameters(record)
        created = self._run(
            f"creating store {record.name!r}", lambda c: c.execute(statement, parameters).rowcount
        )
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
        statement = self._sql(table.READ, columns=table.COLUMNS)
        row = self._read(
            f"reading store {name!r}",
            lambda c: c.execute(statement, (name,)).fetchone(),
            empty=None,
        )
        if row is None:
            raise self._not_found(name)
        return row_to_record(table.store_row(row), dialect=Dialect.POSTGRES)

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
        check_writable(self._setup, location=self._target.location)
        name, *values = table.record_parameters(record)
        parameters = (*values, name, expected_revision)
        write, revision = self._sql(table.WRITE), self._sql(table.REVISION)

        def attempt(connection: psycopg.Connection[TupleRow]) -> tuple[bool, TupleRow | None]:
            if connection.execute(write, parameters).rowcount:
                return True, None
            return False, connection.execute(revision, (name,)).fetchone()

        written, found = self._run(f"writing store {record.name!r}", attempt)
        if written:
            return
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
        check_writable(self._setup, location=self._target.location)
        statement = self._sql(table.DELETE)
        deleted = self._run(
            f"deleting store {name!r}", lambda c: c.execute(statement, (name,)).rowcount
        )
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
            BackendError: The adapter is closed or read-only.
        """
        self._check_open()
        check_writable(self._setup, location=self._target.location)
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
        # The driver's exception is not chained: its text may quote the password, and the
        # redacted copy below is all a traceback may show (CONTRIBUTING §6).
        try:
            if self._setup is SetupMode.READ_ONLY:
                # D54: completion must not hang on a slow server; this overrides the URL's.
                return psycopg.connect(
                    self._target.conninfo,
                    autocommit=True,
                    connect_timeout=READ_ONLY_CONNECT_TIMEOUT,
                )
            return psycopg.connect(self._target.conninfo, autocommit=True)
        except psycopg.Error as err:
            detail = self._target.redact(str(err).strip())
        except UnicodeError:
            # psycopg decodes every connection parameter as UTF-8; its message quotes bytes.
            detail = "a connection parameter is not UTF-8 after percent-decoding"
        message = f"cannot connect to PostgreSQL ({self._target.location}): {detail}"
        raise BackendError(message)

    def _set_up(self, *, auto_upgrade: bool) -> MigrationReport:
        """Inspect, decide and create or upgrade in one locked transaction (D11, D13).

        The transaction first pins the session time zone to UTC; every data operation runs
        after a successful setup.
        """
        schema = self._target.schema
        client_version = self._migrations[-1].version
        try:
            with self._connection.transaction():
                self._connection.execute(_PIN_UTC)
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
            failure = err
        else:
            self._ready = True
            created = state is SetupState.EMPTY
            return MigrationReport(
                from_version=None if created else found,
                to_version=client_version,
                created=created,
            )
        # Raised outside the except block, so that a dropped driver error is not kept as context.
        operation = "setting up the schema"
        raise self._driver_error(operation, failure)

    def _read[T](
        self, operation: str, work: Callable[[psycopg.Connection[TupleRow]], T], *, empty: T
    ) -> T:
        """`_run` for a read; read-only, a missing or empty schema gives `empty` (D54)."""
        self._check_open()
        if self._setup is SetupMode.READ_ONLY and not self._ready and not self._check_read_only():
            return empty
        return self._run(operation, work)

    def _check_read_only(self) -> bool:
        """Inspect without setting up or locking; `False` for a missing or empty schema."""
        try:
            with self._connection.transaction():
                # Plain SETs persist after COMMIT, for the whole session.
                self._connection.execute(_PIN_UTC)
                self._connection.execute(_READ_ONLY_SESSION)
                inspection, _ = inspect_schema(self._connection, self._target.schema)
        except psycopg.Error as err:
            failure = err
        else:
            state = classify(inspection, client_version=self._migrations[-1].version)
            if state is SetupState.EMPTY:
                return False
            decide(state, auto_upgrade=False, location=self._target.location)
            self._ready = True
            return True
        # Raised outside the except block, so that a dropped driver error is not kept as context.
        operation = "checking the schema"
        raise self._driver_error(operation, failure)

    def _run[T](self, operation: str, work: Callable[[psycopg.Connection[TupleRow]], T]) -> T:
        """Run `work` on the connection, after the lazy setup check; wrap driver errors."""
        self._check_open()
        if not self._ready:
            # SetupMode.NONE: the AUTO check runs lazily before the first data operation.
            self._set_up(auto_upgrade=False)
        try:
            return work(self._connection)
        except psycopg.Error as err:
            failure = err
        # Raised outside the except block, so that a dropped driver error is not kept as context.
        raise self._driver_error(operation, failure)

    def _check_open(self) -> None:
        if self._closed:
            message = f"the PostgreSQL adapter for {self._target.location} is closed"
            raise BackendError(message)

    def _driver_error(self, operation: str, err: psycopg.Error) -> BackendError:
        """The `BackendError` for a driver error; raise it outside the `except` block.

        A server error is chained as cause. A client-side error is not: its text may quote the
        connection string and is only shown redacted.
        """
        # Only the primary message of a server error: DETAIL lines may quote stored values.
        if err.sqlstate is None:
            detail = self._target.redact(str(err).strip())
        else:
            detail = f"{err.diag.message_primary} (SQLSTATE {err.sqlstate})"
        message = f"PostgreSQL error while {operation} in {self._target.location}: {detail}"
        error = BackendError(message)
        error.__cause__ = err if err.sqlstate is not None else None
        error.__suppress_context__ = True
        return error

    def _not_found(self, name: str) -> StoreNotFoundError:
        return StoreNotFoundError(f"store {name!r} not found in {self._target.location}")

    def _sql(self, template: sql.SQL, **parts: sql.Composable) -> sql.Composed:
        return template.format(schema=sql.Identifier(self._target.schema), **parts)
