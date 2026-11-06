"""The SQLite adapter: every store is one row of the `stores` table in one file (D8, D10).

Stdlib `sqlite3` only (D6, D10). The connection runs in autocommit mode and every multi-statement
operation opens an explicit transaction, so no read transaction stays open between operations and
an open adapter always sees what other connections committed. WAL mode lets readers work while
one connection writes; the busy timeout makes writers queue instead of failing.

A missing database file is created, with its missing parent directories (mode 0700), by the
first write only (D43): opening and reading a missing file create nothing, they find no stores.
"""

import os
import sqlite3
import threading
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, Self, cast, overload

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
from environment_store.adapters.sqlite.directories import make_private_directory
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
_FILE_MODE: Final = 0o600

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
        url: `sqlite:///relative.db`, `sqlite:////absolute/path.db` or `sqlite:///~/envs.db`.
        setup: `AUTO` inspects an existing file now and creates or upgrades the schema (D11);
            `NONE` defers that to `migrate()` or the first data operation. A missing file is
            set up by the first write.

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
    _closed: bool
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
        """Connect to an existing database file and, with `SetupMode.AUTO`, set it up (D11, D13).

        Args:
            path: The database file; a relative path is resolved against the working
                directory now. A missing file is not created here but by the first write
                (`create_store` or `migrate`), with its missing parent directories (D43).
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
        self._closed = False
        with self._errors():
            self._connect(create=False)
        if setup is SetupMode.AUTO and self._connection is not None:
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
        with self._session(create=False) as connection:
            rows = [] if connection is None else connection.execute(_LIST).fetchall()
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
        with self._session(create=True) as connection:
            inserted = (
                cast("sqlite3.Connection", connection).execute(_INSERT, row.values()).rowcount
            )
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
        with self._session(create=False) as connection:
            row = None if connection is None else connection.execute(_READ, (name,)).fetchone()
        if row is None:
            raise _not_found(name, self.path)
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
        with self._session(create=False) as connection:
            if connection is None:
                raise _not_found(record.name, self.path)
            with transaction(connection, immediate=True):
                if connection.execute(_UPDATE, parameters).rowcount:
                    return
                exists = connection.execute(_EXISTS, (record.name,)).fetchone() is not None
        if not exists:
            raise _not_found(record.name, self.path)
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
        with self._session(create=False) as connection:
            deleted = 0 if connection is None else connection.execute(_DELETE, (name,)).rowcount
        if not deleted:
            raise _not_found(name, self.path)

    def migrate(self) -> MigrationReport:
        """Create (new or empty file) or upgrade (older schema) the schema; no-op when current.

        A missing file is created, with its missing parent directories (D43).

        Returns:
            What was done.

        Raises:
            DatabaseNotCleanError: The file holds foreign content; nothing changed.
            SchemaTooNewError: The schema is newer than this client; nothing changed.
            BackendError: The adapter is closed or the file cannot be written.
        """
        with self._lock, self._errors():
            return self._set_up(self._open_connection(create=True))

    # --- lifecycle ---------------------------------------------------------------------------

    def close(self) -> None:
        """Close the connection; idempotent. The file keeps its data."""
        with self._lock:
            connection, self._connection = self._connection, None
            self._closed = True
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
    def _session(self, *, create: bool) -> Generator[sqlite3.Connection | None]:
        # Exclusive use of the open, set-up connection; driver errors become BackendError.
        # Yields None for a missing file unless `create`: a read finds no stores.
        with self._lock, self._errors():
            connection = self._open_connection(create=create)
            if connection is not None and not self._ready:
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
        except (sqlite3.Error, OSError) as err:
            # OSError: creating the missing directories of the file on the first write.
            message = f"SQLite database {self.path}: {err}"
            raise BackendError(message) from err

    @overload
    def _open_connection(self, *, create: Literal[True]) -> sqlite3.Connection: ...

    @overload
    def _open_connection(self, *, create: bool) -> sqlite3.Connection | None: ...

    def _open_connection(self, *, create: bool) -> sqlite3.Connection | None:
        if self._closed:
            message = f"the SQLite adapter for {self.path} is closed; open a new one"
            raise BackendError(message)
        return self._connect(create=create)

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        # Connects once the file exists (another connection may have created it since open);
        # with `create`, a missing file and its missing directories are created first (D43).
        if self._connection is None:
            if create:
                make_private_directory(self.path.parent)
                _create_private(self.path)
            elif _missing(self.path):
                return None
            # Without `create`, mode=rw: SQLite never creates the file itself (with its default
            # mode, 0644) when it is deleted between the check above and this connect.
            mode = "rwc" if create else "rw"
            try:
                # check_same_thread=False: the lock, not the creating thread, guards the
                # connection.
                connection = sqlite3.connect(
                    f"{self.path.as_uri()}?mode={mode}",
                    timeout=self._busy_timeout,
                    autocommit=True,
                    check_same_thread=False,
                    uri=True,
                )
            except sqlite3.OperationalError:
                if not create and _missing(self.path):
                    return None
                raise
            # Freed pages are zeroed: a deleted or replaced plaintext value leaves no trace.
            connection.execute("PRAGMA secure_delete = ON")
            # The driver's own UTF-8 decode error quotes the whole column (secret values); with
            # surrogateescape invalid bytes reach the codec, which reports them without a value.
            connection.text_factory = _decode_text
            self._connection = connection
        return self._connection


def _not_found(name: str, path: Path) -> StoreNotFoundError:
    return StoreNotFoundError(f"store {name!r} not found in {path}")


def _missing(path: Path) -> bool:
    # Only "does not exist" counts: other errors (no permission, a file as parent) are left to
    # `sqlite3.connect` to report.
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def _create_private(path: Path) -> None:
    """Create a missing database file with mode 0600, like the file backend's store files.

    SQLite gives its -wal and -shm files the database file's mode, so they are private too.
    An existing file keeps its mode; a failure is left to `sqlite3.connect` to report.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    except OSError:
        return
    os.close(fd)


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")
