"""The adapter contract: how the core talks to a storage backend.

Adapters are deliberately dumb. They store and return opaque `StoreRecord`s and know nothing about
encryption, merging or export formats. Every adapter passes the shared contract suite in
`tests/contract/`, which is the executable form of the rules documented here.
"""

from dataclasses import dataclass
from enum import StrEnum, auto
from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from environment_store.core.errors import BackendError, ValidationError
from environment_store.core.models import MAX_REVISION, StoreInfo, StoreRecord
from environment_store.core.validation import validate_store_name

__all__ = [
    "Adapter",
    "MigratableAdapter",
    "MigrationReport",
    "SetupMode",
    "check_create",
    "check_writable",
    "check_write",
]


class SetupMode(StrEnum):
    """How an adapter treats the database layout when it is opened.

    `AUTO` (default): SQL adapters inspect the database on open and create or upgrade it: SQLite
    creates and upgrades automatically, PostgreSQL creates automatically but upgrades only through
    `migrate()`; foreign content or a newer schema is refused. `NONE`: open does not inspect;
    `migrate()` creates or upgrades explicitly and any data operation first runs the `AUTO` check
    lazily. File adapters need no setup.

    `READ_ONLY`: nothing is ever created, set up, upgraded or written, not even a lock or
    journal file. Reads use what is there: an empty database or a missing location
    holds no stores, a schema that would need creating or upgrading is refused. Every write and
    `migrate()` raises `BackendError`. Meant for quick lookups such as shell completion; the
    PostgreSQL adapter also bounds every wait in this mode: the connect over all hosts, each
    query and lock wait, and a stalled network.
    """

    # auto() gives the lowercase member name: "auto", "none", "read_only".
    AUTO = auto()
    NONE = auto()
    READ_ONLY = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationReport:
    """What `MigratableAdapter.migrate()` did.

    Attributes:
        from_version: The schema version found, or `None` if the schema was created.
        to_version: The schema version after migrating.
        created: Whether the schema was created from scratch.
    """

    from_version: int | None
    to_version: int
    created: bool

    def __post_init__(self) -> None:
        """Validate the report.

        Raises:
            ValidationError: A version is not an integer >= 1, the schema went backwards, or
                `created` does not match a missing `from_version`.
        """
        _check_version(self.to_version, "to_version")
        if self.from_version is not None:
            _check_version(self.from_version, "from_version")
            if self.from_version > self.to_version:
                message = "a migration never moves the schema to an older version"
                raise ValidationError(message)
        if self.created != (self.from_version is None):
            message = "created must be true exactly when there was no schema (from_version None)"
            raise ValidationError(message)


@runtime_checkable
class Adapter(Protocol):
    """A storage backend for store records.

    Rules every implementation follows (checked by the contract suite):

    - Every method validates the store names it receives (defense in depth; the service
      validates first) and checks its arguments before it touches the backend.
    - Every OS, driver or I/O failure is raised as `BackendError`, chained, never raw.
    - Writes are atomic and guarded by the revision check: nothing is ever overwritten
      silently.
    - After `close()` (or leaving the `with` block) every data operation raises `BackendError`;
      closing twice is harmless.
    """

    def list_stores(self) -> list[StoreInfo]:
        """List every store without decrypting anything.

        Returns:
            One entry per store, sorted by name (code point order).
        """
        ...

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store; atomic, so of two racing creates exactly one wins.

        Args:
            record: The new store; its revision must be 1.

        Raises:
            ValidationError: Invalid name or a revision other than 1.
            StoreExistsError: A store with this name exists.
        """
        ...

    def read_store(self, name: str) -> StoreRecord:
        """Read a complete store record.

        Args:
            name: The store name.

        Returns:
            The record exactly as it was written.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
        """
        ...

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store atomically if nobody changed it since it was read.

        Args:
            record: The new content; its revision must be `expected_revision + 1`.
            expected_revision: The revision that was read.

        Raises:
            ValidationError: Invalid name or revisions.
            StoreNotFoundError: The store does not exist.
            ConcurrentModificationError: The stored revision differs; nothing was written.
        """
        ...

    def delete_store(self, name: str) -> None:
        """Delete a store.

        Args:
            name: The store name.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
        """
        ...

    def close(self) -> None:
        """Release every resource; idempotent."""
        ...

    def __enter__(self) -> Self:
        """Return the adapter itself."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the adapter; never suppresses an exception."""
        ...


@runtime_checkable
class MigratableAdapter(Adapter, Protocol):
    """An adapter with a versioned schema: the SQL adapters."""

    def migrate(self) -> MigrationReport:
        """Create (empty database) or upgrade (older schema) the schema; no-op when current.

        Returns:
            What was done.

        Raises:
            DatabaseNotCleanError: The database holds foreign content.
            SchemaTooNewError: The schema is newer than this client.
        """
        ...


def check_writable(setup: SetupMode, *, location: str) -> None:
    """Refuse a write of an adapter opened with `SetupMode.READ_ONLY`.

    Args:
        setup: The mode the adapter was opened with.
        location: Where the stores are, for the message (never credentials).

    Raises:
        BackendError: The adapter is read-only; nothing was touched.
    """
    if setup is SetupMode.READ_ONLY:
        message = f"{location} was opened read-only and cannot be changed"
        raise BackendError(message)


def check_create(record: StoreRecord) -> None:
    """Check the arguments of `Adapter.create_store` before touching the backend.

    Args:
        record: The new store.

    Raises:
        ValidationError: The name is invalid or the revision is not 1.
    """
    validate_store_name(record.name)
    if record.revision != 1:
        message = f"store {record.name!r}: a new store starts at revision 1, got {record.revision}"
        raise ValidationError(message)


def check_write(record: StoreRecord, *, expected_revision: int) -> None:
    """Check the arguments of `Adapter.write_store` before touching the backend.

    Args:
        record: The new content.
        expected_revision: The revision that was read.

    Raises:
        ValidationError: The name is invalid, `expected_revision` is not an integer >= 1 or is
            `MAX_REVISION` or larger (it cannot be incremented), or the record's revision is not
            `expected_revision + 1`.
    """
    validate_store_name(record.name)
    _check_version(expected_revision, "expected_revision")
    if expected_revision >= MAX_REVISION:
        message = (
            f"store {record.name!r}: expected_revision {expected_revision} cannot be incremented, "
            f"revisions go up to {MAX_REVISION}"
        )
        raise ValidationError(message)
    if record.revision != expected_revision + 1:
        message = (
            f"store {record.name!r}: the written record must have revision "
            f"{expected_revision + 1} (expected_revision + 1), got {record.revision}"
        )
        raise ValidationError(message)


def _check_version(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        message = f"{name} must be an integer >= 1, got {value!r}"
        raise ValidationError(message)
