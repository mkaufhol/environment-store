"""Exception hierarchy of Environment Store.

Every error derives from `EnvironmentStoreError`. The direct subclasses are *categories*; the CLI
maps each category to an exit code (D24):

| Category | Exit code |
|---|---|
| `ValidationError`, `ConfigurationError`, `MissingExtraError`, `BackendError` | 1 |
| `NotFoundError` | 2 |
| `AlreadyExistsError` | 3 |
| `CryptoError` | 4 |
| `ConcurrentModificationError` | 5 |

Messages never contain keys, passphrases or variable values.
"""

from collections.abc import Iterable

__all__ = [
    "AlreadyEncryptedError",
    "AlreadyExistsError",
    "BackendError",
    "ConcurrentModificationError",
    "ConfigurationError",
    "CryptoError",
    "DatabaseNotCleanError",
    "DecryptionError",
    "EnvironmentStoreError",
    "InvalidKeyFileError",
    "KeyModeMismatchError",
    "KeyRequiredError",
    "KeySourceError",
    "MissingExtraError",
    "NotEncryptedError",
    "NotFoundError",
    "PlaintextNotAllowedError",
    "SchemaOutdatedError",
    "SchemaTooNewError",
    "SetupPrivilegeError",
    "StoreExistsError",
    "StoreNotFoundError",
    "UnsupportedFormatError",
    "ValidationError",
    "VariableExistsError",
    "VariableNotFoundError",
]


class EnvironmentStoreError(Exception):
    """Root of all Environment Store errors."""


# --- exit code 1 -------------------------------------------------------------------------------


class ValidationError(EnvironmentStoreError, ValueError):
    """Invalid names, values, URLs or arguments."""


class AlreadyEncryptedError(ValidationError):
    """The store is already encrypted (`encrypt` on an encrypted store, D4)."""


class NotEncryptedError(ValidationError):
    """The store is not encrypted, e.g. a secret was given for a plaintext store."""


class PlaintextNotAllowedError(ValidationError):
    """Plaintext input is refused for an encrypted store (e.g. `KEY=VALUE` arguments, D18)."""


class ConfigurationError(EnvironmentStoreError):
    """Missing connection (D29), bad environment values or project file problems."""


class MissingExtraError(EnvironmentStoreError):
    """An optional dependency is not installed.

    Attributes:
        extra: Name of the pip extra that provides the dependency.
    """

    extra: str

    def __init__(self, extra: str) -> None:
        """Create the error for a missing extra.

        Args:
            extra: Name of the pip extra that provides the dependency, e.g. `postgres`.
        """
        message = (
            f"this feature needs the optional '{extra}' dependencies: "
            f"pip install 'environment-store[{extra}]'"
        )
        super().__init__(message)
        self.extra = extra


class BackendError(EnvironmentStoreError):
    """An OS, driver or I/O failure of a backend; never contains credentials."""


class UnsupportedFormatError(BackendError):
    """Unknown file format, cipher, key mode or KDF, or out-of-bounds KDF parameters."""


class DatabaseNotCleanError(BackendError):
    """The database contains foreign content; nothing is created or changed (D13)."""


class SchemaOutdatedError(BackendError):
    """The database schema is older than this client and must be migrated (D11)."""


class SchemaTooNewError(BackendError):
    """The database schema is newer than this client (D13)."""


class SetupPrivilegeError(BackendError):
    """The database user may not create the schema during the first setup (D11)."""


# --- exit code 2 -------------------------------------------------------------------------------


class NotFoundError(EnvironmentStoreError):
    """A store or variable does not exist."""


class StoreNotFoundError(NotFoundError):
    """The store does not exist."""


class VariableNotFoundError(NotFoundError):
    """One or more variables do not exist in a store.

    Attributes:
        names: All missing variable names, in the order given.
        store: The store that was searched.
    """

    names: tuple[str, ...]
    store: str

    def __init__(self, names: Iterable[str], *, store: str) -> None:
        """Create the error listing every missing variable.

        Args:
            names: The missing variable names.
            store: The store that was searched.
        """
        self.names = tuple(names)
        self.store = store
        message = f"variables not found in store '{store}': {', '.join(self.names)}"
        super().__init__(message)


# --- exit code 3 -------------------------------------------------------------------------------


class AlreadyExistsError(EnvironmentStoreError):
    """A store or variable exists already."""


class StoreExistsError(AlreadyExistsError):
    """The store exists already."""


class VariableExistsError(AlreadyExistsError):
    """One or more variables exist already and overwriting was not requested (D18).

    Attributes:
        names: All conflicting variable names, in the order given.
        store: The store that holds them.
    """

    names: tuple[str, ...]
    store: str

    def __init__(self, names: Iterable[str], *, store: str) -> None:
        """Create the error listing every conflicting variable.

        Args:
            names: The conflicting variable names.
            store: The store that holds them.
        """
        self.names = tuple(names)
        self.store = store
        message = (
            f"variables already exist in store '{store}': {', '.join(self.names)}; "
            "use overwrite (-o/--overwrite) to replace them"
        )
        super().__init__(message)


# --- exit code 4 -------------------------------------------------------------------------------


class CryptoError(EnvironmentStoreError):
    """Decryption or key error."""


class KeyRequiredError(CryptoError):
    """The store is encrypted and no key or passphrase was given."""


class DecryptionError(CryptoError):
    """Decryption failed: wrong key, tampered data or changed metadata (D5)."""


class InvalidKeyFileError(CryptoError):
    """The text is not a valid key file (`envstore-key-v1:...`)."""


class KeyModeMismatchError(CryptoError):
    """The secret does not match the store's key mode (key file vs. passphrase)."""


class KeySourceError(CryptoError):
    """A key or passphrase cannot be read: missing or unreadable file, not UTF-8, or empty.

    A missing key file is a key error like a missing key (PD 3), so it shares exit code 4. The
    message names the source (a path or stdin), never its content.
    """


# --- exit code 5 -------------------------------------------------------------------------------


class ConcurrentModificationError(EnvironmentStoreError):
    """The store was changed since it was read; nothing was written (D7)."""
