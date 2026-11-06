"""The JSON and TOML file adapters: one file per store in a directory (D9, spec §3.2).

- `<directory>/<store>.json` (or `.toml`) holds one store; the store name is the file stem.
  Files with another extension or a stem that is not a valid store name (D27) are ignored.
- Create, write and delete run under the store's lock file `.<store>.<ext>.lock` (D7). A write
  checks the revision under the lock, writes a temporary file in the same directory and moves it
  into place with `os.replace`, so readers see the old or the new file, never a mix.
- Create publishes the temporary file with a hard link (`os.link`), which fails if the store
  file exists: the `O_EXCL` semantics that let exactly one of two racing creates win.
"""

import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from environment_store.adapters.files.layout import (
    document_to_info,
    document_to_record,
    record_to_document,
)
from environment_store.adapters.files.locking import exclusive_lock
from environment_store.adapters.files.serializers import (
    JSON_SERIALIZER,
    TOML_SERIALIZER,
    FileSerializer,
)
from environment_store.adapters.files.url import directory_from_url
from environment_store.core.adapter import SetupMode, check_create, check_write
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    StoreExistsError,
    StoreNotFoundError,
)
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.core.validation import STORE_NAME_PATTERN, validate_store_name

__all__ = ["DEFAULT_LOCK_TIMEOUT", "FileAdapter", "open_json", "open_toml"]

DEFAULT_LOCK_TIMEOUT: Final[float] = 10.0
"""Seconds a write waits for another writer of the same store before it fails."""


def open_json(url: str, *, setup: SetupMode = SetupMode.AUTO) -> "FileAdapter":
    """Open a `json://` store directory.

    Args:
        url: `json://relative/dir`, `json:///absolute/dir` or `json://~/dir`.
        setup: Accepted for the common factory signature and ignored: files need no setup.

    Returns:
        The adapter.

    Raises:
        ValidationError: The connection string is not a valid `json://` URL.
    """
    return FileAdapter(
        directory_from_url(url, scheme="json"), serializer=JSON_SERIALIZER, setup=setup
    )


def open_toml(url: str, *, setup: SetupMode = SetupMode.AUTO) -> "FileAdapter":
    """Open a `toml://` store directory.

    Args:
        url: `toml://relative/dir`, `toml:///absolute/dir` or `toml://~/dir`.
        setup: Accepted for the common factory signature and ignored: files need no setup.

    Returns:
        The adapter.

    Raises:
        ValidationError: The connection string is not a valid `toml://` URL.
    """
    return FileAdapter(
        directory_from_url(url, scheme="toml"), serializer=TOML_SERIALIZER, setup=setup
    )


class FileAdapter:
    """An `Adapter` that keeps one file per store in a directory.

    Attributes:
        directory: The store directory; created on the first write.
        serializer: The file format.
        setup: The setup mode it was opened with (accepted and ignored).
        lock_timeout: Seconds to wait for another writer of the same store.
    """

    directory: Path
    serializer: FileSerializer
    setup: SetupMode
    lock_timeout: float
    _closed: bool

    def __init__(
        self,
        directory: Path,
        *,
        serializer: FileSerializer,
        setup: SetupMode = SetupMode.AUTO,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        """Create the adapter; nothing is touched on disk until the first operation.

        Args:
            directory: The store directory.
            serializer: The file format.
            setup: Accepted and ignored, like by every file adapter.
            lock_timeout: Seconds to wait for another writer of the same store.
        """
        self.directory = directory
        self.serializer = serializer
        self.setup = setup
        self.lock_timeout = lock_timeout
        self._closed = False

    # --- Adapter -------------------------------------------------------------------------------

    def list_stores(self) -> list[StoreInfo]:
        """List every store, sorted by name (code point order).

        Returns:
            One entry per store file.

        Raises:
            BackendError: The directory or a store file cannot be read, or a file is corrupt.
        """
        self._check_open()
        infos: list[StoreInfo] = []
        for name in self._store_names():
            try:
                document = self._load(name)
            except StoreNotFoundError:
                continue  # deleted since the directory was listed
            infos.append(
                document_to_info(
                    document,
                    name=name,
                    source=str(self._path(name)),
                    parse_timestamp=self.serializer.parse_timestamp,
                )
            )
        return infos

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store file; of two racing creates exactly one wins.

        Args:
            record: The new store at revision 1.

        Raises:
            ValidationError: Invalid name or revision.
            StoreExistsError: The store file exists.
            BackendError: An OS failure or a lock timeout.
        """
        check_create(record)
        self._check_open()
        text = self.serializer.dumps(record_to_document(record))
        with self._os_errors(f"create store {record.name!r}"):
            self.directory.mkdir(parents=True, exist_ok=True)
            with self._lock(record.name):
                try:
                    self._publish(text, record.name, exclusive=True)
                except FileExistsError:
                    message = f"store {record.name!r} already exists in {self.directory}"
                    raise StoreExistsError(message) from None

    def read_store(self, name: str) -> StoreRecord:
        """Read a store file.

        Args:
            name: The store name.

        Returns:
            The record.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store file does not exist.
            UnsupportedFormatError: Unknown file format or cipher metadata.
            BackendError: An OS failure or a corrupt file.
        """
        validate_store_name(name)
        self._check_open()
        return document_to_record(
            self._load(name),
            name=name,
            source=str(self._path(name)),
            parse_timestamp=self.serializer.parse_timestamp,
        )

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store file if its revision is still `expected_revision` (D7).

        Args:
            record: The new content at revision `expected_revision + 1`.
            expected_revision: The revision that was read.

        Raises:
            ValidationError: Invalid name or revisions.
            StoreNotFoundError: The store file does not exist.
            ConcurrentModificationError: The stored revision differs; nothing was written.
            BackendError: An OS failure, a lock timeout or a corrupt file.
        """
        check_write(record, expected_revision=expected_revision)
        self._check_open()
        text = self.serializer.dumps(record_to_document(record))
        with self._os_errors(f"write store {record.name!r}"):
            self._require_file(record.name)
            with self._lock(record.name):
                stored = document_to_info(
                    self._load(record.name),
                    name=record.name,
                    source=str(self._path(record.name)),
                    parse_timestamp=self.serializer.parse_timestamp,
                )
                if stored.revision != expected_revision:
                    message = (
                        f"store {record.name!r} was changed concurrently: revision "
                        f"{stored.revision}, expected {expected_revision}; read it again"
                    )
                    raise ConcurrentModificationError(message)
                self._publish(text, record.name, exclusive=False)

    def delete_store(self, name: str) -> None:
        """Delete a store file.

        Args:
            name: The store name.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store file does not exist.
            BackendError: An OS failure or a lock timeout.
        """
        validate_store_name(name)
        self._check_open()
        with self._os_errors(f"delete store {name!r}"):
            self._require_file(name)
            with self._lock(name):
                try:
                    self._path(name).unlink()
                except FileNotFoundError:
                    raise self._not_found(name) from None

    def close(self) -> None:
        """Close the adapter; it holds no open resources between operations."""
        self._closed = True

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

    # --- helpers -------------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._closed:
            message = f"the file adapter for {self.directory} is closed"
            raise BackendError(message)

    def _path(self, name: str) -> Path:
        # Safe: every caller validated `name` against D27, which allows no separators or dots.
        return self.directory / f"{name}{self.serializer.extension}"

    def _not_found(self, name: str) -> StoreNotFoundError:
        return StoreNotFoundError(f"store {name!r} not found in {self.directory}")

    @contextmanager
    def _os_errors(self, action: str) -> Generator[None]:
        try:
            yield
        except OSError as err:
            message = f"could not {action} in {self.directory}: {err}"
            raise BackendError(message) from err

    @contextmanager
    def _lock(self, name: str) -> Generator[None]:
        lock = self.directory / f".{name}{self.serializer.extension}.lock"
        with exclusive_lock(lock, timeout=self.lock_timeout):
            yield

    def _store_names(self) -> list[str]:
        with self._os_errors("list stores"):
            try:
                entries = list(self.directory.iterdir())
            except FileNotFoundError:
                return []
            return sorted(
                entry.stem
                for entry in entries
                if entry.suffix == self.serializer.extension
                and STORE_NAME_PATTERN.fullmatch(entry.stem)
                and entry.is_file()
            )

    def _require_file(self, name: str) -> None:
        # Checked before locking, so that a missing store creates no lock file (or directory).
        try:
            self._path(name).stat()
        except FileNotFoundError:
            raise self._not_found(name) from None

    def _load(self, name: str) -> object:
        path = self._path(name)
        with self._os_errors(f"read store {name!r}"):
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                raise self._not_found(name) from None
        try:
            return self.serializer.loads(data.decode("utf-8"))
        except (ValueError, RecursionError) as err:
            # ValueError covers UnicodeDecodeError and the parsers' errors. Their messages are
            # not used: they may quote the (secret) file content.
            message = f"corrupt store file {path}: not valid UTF-8 {self.serializer.name}"
            raise BackendError(message) from err

    def _publish(self, text: str, name: str, *, exclusive: bool) -> None:
        target = self._path(name)
        fd, temp_name = tempfile.mkstemp(
            dir=self.directory, prefix=f".{target.name}.", suffix=".tmp"
        )
        temp = Path(temp_name)
        try:
            # newline="": write "\n" as is on every platform, so files are identical everywhere.
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if exclusive:
                os.link(temp, target)
            else:
                temp.replace(target)
        finally:
            # Gone after os.replace; still there after os.link or a failure.
            temp.unlink(missing_ok=True)
