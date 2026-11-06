"""The SQLite adapter: every store is one row of the `stores` table in one file (D8, D10).

Stdlib `sqlite3` only (D6, D10). The connection runs in autocommit mode and every multi-statement
operation opens an explicit transaction, so no read transaction stays open between operations and
an open adapter always sees what other connections committed. WAL mode lets readers work while
one connection writes; the busy timeout makes writers queue instead of failing.
"""

import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from environment_store.adapters.sql.codec import (
    Dialect,
    StoreInfoRow,
    StoreRow,
    record_to_row,
    row_to_info,
    row_to_record,
)
from environment_store.adapters.sql.migrations import SQLITE_MIGRATIONS, Migration, pending
from environment_store.adapters.sql.schema import STORE_INFO_COLUMNS, STORES_COLUMNS
from environment_store.adapters.sqlite.schema import set_up, transaction
from environment_store.adapters.sqlite.url import parse_sqlite_url
from environment_store.core.adapter import (
    MigrationReport,
    SetupMode,
    check_create,
    check_write,
)
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.core.validation import validate_store_name

__all__ = ["BUSY_TIMEOUT_SECONDS", "SqliteAdapter", "open_sqlite"]

BUSY_TIMEOUT_SECONDS: Final[float] = 30.0
"""How long a connection waits for another connection's lock before failing."""

# Literal statements with parameters only; the column lists match STORES_COLUMNS and
# STORE_INFO_COLUMNS (checked by the tests).
_LIST: Final = "SELECT name, encrypted, cipher_meta, revision, created_at, updated_at FROM stores"
_READ: Final = (
    "SELECT name, encrypted, cipher_meta, variables, ciphertext, revision, created_at, "
    "updated_at FROM stores WHERE name = ?"
)
_INSERT: Final = (
    "INSERT INTO stores (name, encrypted, cipher_meta, variables, ciphertext, revision, "
    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (name) DO NOTHING"
)
# The revision check and the replacement are one statement (D7).
_UPDATE: Final = (
    "UPDATE stores SET encrypted = ?, cipher_meta = ?, variables = ?, ciphertext = ?, "
    "revision = revision + 1, created_at = ?, updated_at = ? WHERE name = ? AND revision = ?"
)
_EXISTS: Final = "SELECT 1 FROM stores WHERE name = ?"
_DELETE: Final = "DELETE FROM stores WHERE name = ?"


def open_sqlite(url: str, /, *, setup: SetupMode = SetupMode.AUTO) -> "SqliteAdapter":
    """Open the SQLite adapter for a connection string (the `sqlite` scheme factory).

    Args:
        url: `sqlite:///relative.db` or `sqlite:////absolute/path.db`.
        setup: `AUTO` inspects the file now and creates or upgrades the schema (D11);
            `NONE` defers that to `migrate()` or the first data operation.

    Returns:
        The open adapter.

    Raises:
        ValidationError: The connection string names no database file.
        BackendError: The file cannot be opened, or is refused (see `SqliteAdapter`).
    """
    return SqliteAdapter(parse_sqlite_url(url), setup=setup)


class SqliteAdapter:
    """An `Adapter` (and `MigratableAdapter`) on one SQLite database file.

    One instance holds one connection; a lock serialises its use from several threads.

    Attributes:
        path: The absolute path of the database file.
        setup: The setup mode it was opened with.
    """

    path: Path
    setup: SetupMode
    _migrations: tuple[Migration, ...]
    _busy_timeout: float
    _connection: sqlite3.Connection | None
    _ready: bool
    _lock: threading.Lock

    def __init__(
        self,
        path: Path,
        *,
        setup: SetupMode = SetupMode.AUTO,
        migrations: Sequence[Migration] = SQLITE_MIGRATIONS,
        busy_timeout: float = BUSY_TIMEOUT_SECONDS,
    ) -> None:
        """Connect to the database file and, with `SetupMode.AUTO`, set it up (D11, D13).

        Args:
            path: The database file; a relative path is resolved against the working
                directory now. A missing file is created, its directory is not.
            setup: When the schema is checked: now (`AUTO`) or lazily (`NONE`).
            migrations: The dialect's migrations; the last one is this client's schema
                version. Tests pass their own to exercise upgrades.
            busy_timeout: Seconds to wait for locks held by other connections.

        Raises:
            ValidationError: The migrations are not numbered 1 to n, or the busy timeout is
                not positive.
            DatabaseNotCleanError: The file holds foreign content (`AUTO`); nothing changed.
            SchemaTooNewError: The schema is newer than this client (`AUTO`); nothing changed.
            BackendError: The file cannot be opened or read.
        """
        pending(migrations, None)  # validates the numbering
        if not busy_timeout > 0:
            message = f"the SQLite busy timeout must be positive (seconds), got {busy_timeout!r}"
            raise ValidationError(message)
        self.path = path.absolute()
        self.setup = setup
        self._migrations = tuple(migrations)
        self._busy_timeout = busy_timeout
        self._ready = False
        self._lock = threading.Lock()
        self._connection = None
        with self._errors():
            # check_same_thread=False: the lock, not the creating thread, guards the connection.
            self._connection = sqlite3.connect(
                self.path, timeout=busy_timeout, autocommit=True, check_same_thread=False
            )
            # The driver's own UTF-8 decode error quotes the whole column (secret values); with
            # surrogateescape invalid bytes reach the codec, which reports them without a value.
            self._connection.text_factory = _decode_text
        if setup is SetupMode.AUTO:
            # On SQLite, the AUTO check is exactly migrate(): create, upgrade or use (D11).
            try:
                self.migrate()
            except BaseException:
                self.close()
                raise

    # --- data operations ---------------------------------------------------------------------

    def list_stores(self) -> list[StoreInfo]:
        """List every store without reading the payloads.

        Returns:
            One entry per store, sorted by name in code point order.
        """
        with self._session() as connection:
            rows = connection.execute(_LIST).fetchall()
        infos = [
            row_to_info(
                StoreInfoRow(**dict(zip(STORE_INFO_COLUMNS, row, strict=True))),
                dialect=Dialect.SQLITE,
            )
            for row in rows
        ]
        return sorted(infos, key=lambda info: info.name)

    def create_store(self, record: StoreRecord) -> None:
        """Insert a new store; of two racing creates exactly one wins.

        Args:
            record: The new store at revision 1.

        Raises:
            ValidationError: Invalid name or a revision other than 1.
            StoreExistsError: A store with this name exists.
        """
        check_create(record)
        row = record_to_row(record, dialect=Dialect.SQLITE)
        with self._session() as connection:
            inserted = connection.execute(_INSERT, row.values()).rowcount
        if not inserted:
            message = f"store {record.name!r} already exists"
            raise StoreExistsError(message)

    def read_store(self, name: str) -> StoreRecord:
        """Read a complete store record.

        Args:
            name: The store name.

        Returns:
            The record as it was written.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
            BackendError: The row is corrupt.
        """
        validate_store_name(name)
        with self._session() as connection:
            row = connection.execute(_READ, (name,)).fetchone()
        if row is None:
            raise _not_found(name)
        return row_to_record(
            StoreRow(**dict(zip(STORES_COLUMNS, row, strict=True))), dialect=Dialect.SQLITE
        )

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store in one `UPDATE ... WHERE revision = ?` (D7).

        Args:
            record: The new content at revision `expected_revision + 1`.
            expected_revision: The revision that was read.

        Raises:
            ValidationError: Invalid name or revisions, including an `expected_revision` that
                cannot be incremented (`MAX_REVISION`, checked by `check_write`).
            StoreNotFoundError: The store does not exist.
            ConcurrentModificationError: The stored revision differs; nothing was written.
        """
        check_write(record, expected_revision=expected_revision)
        row = record_to_row(record, dialect=Dialect.SQLITE)
        parameters = (
            row.encrypted,
            row.cipher_meta,
            row.variables,
            row.ciphertext,
            row.created_at,
            row.updated_at,
            row.name,
            expected_revision,
        )
        with self._session() as connection, transaction(connection, immediate=True):
            if connection.execute(_UPDATE, parameters).rowcount:
                return
            exists = connection.execute(_EXISTS, (record.name,)).fetchone() is not None
        if not exists:
            raise _not_found(record.name)
        message = (
            f"store {record.name!r} was changed concurrently (expected revision "
            f"{expected_revision}); nothing was written, read it again and retry"
        )
        raise ConcurrentModificationError(message)

    def delete_store(self, name: str) -> None:
        """Delete a store.

        Args:
            name: The store name.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
        """
        validate_store_name(name)
        with self._session() as connection:
            deleted = connection.execute(_DELETE, (name,)).rowcount
        if not deleted:
            raise _not_found(name)

    def migrate(self) -> MigrationReport:
        """Create (new or empty file) or upgrade (older schema) the schema; no-op when current.

        Returns:
            What was done.

        Raises:
            DatabaseNotCleanError: The file holds foreign content; nothing changed.
            SchemaTooNewError: The schema is newer than this client; nothing changed.
            BackendError: The adapter is closed or the file cannot be written.
        """
        with self._lock, self._errors():
            return self._set_up(self._open_connection())

    # --- lifecycle ---------------------------------------------------------------------------

    def close(self) -> None:
        """Close the connection; idempotent. The file keeps its data."""
        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                connection.close()

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

    # --- helpers -----------------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Generator[sqlite3.Connection]:
        # Exclusive use of the open, set-up connection; driver errors become BackendError.
        with self._lock, self._errors():
            connection = self._open_connection()
            if not self._ready:
                self._set_up(connection)
            yield connection

    def _set_up(self, connection: sqlite3.Connection) -> MigrationReport:
        report = set_up(
            connection,
            migrations=self._migrations,
            location=str(self.path),
            busy_timeout=self._busy_timeout,
        )
        self._ready = True
        return report

    @contextmanager
    def _errors(self) -> Generator[None]:
        try:
            yield
        except sqlite3.Error as err:
            message = f"SQLite database {self.path}: {err}"
            raise BackendError(message) from err

    def _open_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            message = f"the SQLite adapter for {self.path} is closed; open a new one"
            raise BackendError(message)
        return self._connection


def _not_found(name: str) -> StoreNotFoundError:
    return StoreNotFoundError(f"store {name!r} not found")


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")
