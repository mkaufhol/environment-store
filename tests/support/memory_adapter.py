"""In-memory reference implementation of the adapter contract.

`MemoryBackend` holds the stores; every `MemoryAdapter` opened on it is an independent instance
on the same data, like two connections to one database. Used by the core tests as a fake and as
the contract suite's own reference.
"""

import threading
from types import TracebackType
from typing import Self

from environment_store.core.adapter import SetupMode, check_create, check_writable, check_write
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    StoreExistsError,
    StoreNotFoundError,
)
from environment_store.core.models import StoreInfo, StoreRecord
from environment_store.core.validation import validate_store_name

__all__ = ["MemoryAdapter", "MemoryBackend"]


class MemoryBackend:
    """Shared in-memory storage; a lock makes every operation atomic."""

    _records: dict[str, StoreRecord]
    _lock: threading.Lock

    def __init__(self) -> None:
        self._records = {}
        self._lock = threading.Lock()

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> "MemoryAdapter":
        """Open a new adapter instance on this backend."""
        return MemoryAdapter(self, setup=setup)

    def infos(self) -> list[StoreInfo]:
        """Listing entries sorted by name."""
        with self._lock:
            return [self._records[name].info for name in sorted(self._records)]

    def create(self, record: StoreRecord) -> None:
        """Insert a new record or raise `StoreExistsError`."""
        with self._lock:
            if record.name in self._records:
                message = f"store {record.name!r} already exists"
                raise StoreExistsError(message)
            self._records[record.name] = record

    def read(self, name: str) -> StoreRecord:
        """Return a record or raise `StoreNotFoundError`."""
        with self._lock:
            return self._get(name)

    def replace(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a record if its stored revision is `expected_revision`."""
        with self._lock:
            stored = self._get(record.name)
            if stored.revision != expected_revision:
                message = (
                    f"store {record.name!r} was changed concurrently: revision "
                    f"{stored.revision}, expected {expected_revision}"
                )
                raise ConcurrentModificationError(message)
            self._records[record.name] = record

    def delete(self, name: str) -> None:
        """Remove a record or raise `StoreNotFoundError`."""
        with self._lock:
            self._get(name)
            del self._records[name]

    def _get(self, name: str) -> StoreRecord:
        try:
            return self._records[name]
        except KeyError:
            message = f"store {name!r} not found"
            raise StoreNotFoundError(message) from None


class MemoryAdapter:
    """An `Adapter` on a `MemoryBackend`.

    Attributes:
        backend: The shared storage.
        setup: The setup mode it was opened with; `READ_ONLY` refuses writes.
    """

    backend: MemoryBackend
    setup: SetupMode
    _closed: bool

    def __init__(
        self, backend: MemoryBackend | None = None, *, setup: SetupMode = SetupMode.AUTO
    ) -> None:
        self.backend = MemoryBackend() if backend is None else backend
        self.setup = setup
        self._closed = False

    def list_stores(self) -> list[StoreInfo]:
        """List every store, sorted by name."""
        self._check_open()
        return self.backend.infos()

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store at revision 1."""
        check_create(record)
        self._check_open()
        check_writable(self.setup, location="the memory backend")
        self.backend.create(record)

    def read_store(self, name: str) -> StoreRecord:
        """Read a store."""
        validate_store_name(name)
        self._check_open()
        return self.backend.read(name)

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store if nobody changed it since `expected_revision` was read."""
        check_write(record, expected_revision=expected_revision)
        self._check_open()
        check_writable(self.setup, location="the memory backend")
        self.backend.replace(record, expected_revision=expected_revision)

    def delete_store(self, name: str) -> None:
        """Delete a store."""
        validate_store_name(name)
        self._check_open()
        check_writable(self.setup, location="the memory backend")
        self.backend.delete(name)

    def close(self) -> None:
        """Close this instance; the backend keeps its data."""
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
        """Close the adapter."""
        self.close()

    def _check_open(self) -> None:
        if self._closed:
            message = "the memory adapter is closed"
            raise BackendError(message)
