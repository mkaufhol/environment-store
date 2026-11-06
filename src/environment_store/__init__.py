"""Environment Store: named, optionally encrypted stores of environment variables.

The public API (spec §7.3) is resolved lazily (PD 1): `import environment_store` stays cheap,
and importing a lower layer such as `environment_store.core` never loads the library, the
configuration or the crypto layers.

Example:
    ```python
    import environment_store

    environment_store.load("base_conf", "staging_env")
    ```
"""

import importlib
from importlib.metadata import version
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from environment_store.config.settings import CredentialsInProjectFileWarning
    from environment_store.core.adapter import MigrationReport, SetupMode
    from environment_store.core.errors import (
        AlreadyEncryptedError,
        AlreadyExistsError,
        BackendError,
        ConcurrentModificationError,
        ConfigurationError,
        CryptoError,
        DatabaseNotCleanError,
        DecryptionError,
        EnvironmentStoreError,
        InvalidKeyFileError,
        KeyModeMismatchError,
        KeyRequiredError,
        KeySourceError,
        MissingExtraError,
        NotEncryptedError,
        NotFoundError,
        PlaintextNotAllowedError,
        SchemaOutdatedError,
        SchemaTooNewError,
        SetupPrivilegeError,
        StoreExistsError,
        StoreNotFoundError,
        UnsupportedFormatError,
        ValidationError,
        VariableExistsError,
        VariableNotFoundError,
    )
    from environment_store.core.merge import MergeOrder
    from environment_store.core.models import KeyMode, StoreInfo
    from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
    from environment_store.formats.infer import Format
    from environment_store.library.environment import Environment
    from environment_store.library.keys import generate_key_file, generate_key_text
    from environment_store.library.oneliner import load
    from environment_store.library.sources import KeyInput, Source
    from environment_store.library.store import EnvironmentStore

__version__: str = version("environment-store")

# Module -> the public names it defines.
_DEFINITIONS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("environment_store.library.store", ("EnvironmentStore",)),
    ("environment_store.library.environment", ("Environment",)),
    ("environment_store.library.sources", ("KeyInput", "Source")),
    ("environment_store.library.oneliner", ("load",)),
    ("environment_store.library.keys", ("generate_key_file", "generate_key_text")),
    ("environment_store.config.settings", ("CredentialsInProjectFileWarning",)),
    ("environment_store.core.secrets", ("KeyMaterial", "Passphrase", "Secret")),
    ("environment_store.core.models", ("KeyMode", "StoreInfo")),
    ("environment_store.core.merge", ("MergeOrder",)),
    ("environment_store.formats.infer", ("Format",)),
    ("environment_store.core.adapter", ("MigrationReport", "SetupMode")),
    (
        "environment_store.core.errors",
        (
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
        ),
    ),
)
_LAZY: Final = MappingProxyType({name: module for module, names in _DEFINITIONS for name in names})

__all__ = [
    "AlreadyEncryptedError",
    "AlreadyExistsError",
    "BackendError",
    "ConcurrentModificationError",
    "ConfigurationError",
    "CredentialsInProjectFileWarning",
    "CryptoError",
    "DatabaseNotCleanError",
    "DecryptionError",
    "Environment",
    "EnvironmentStore",
    "EnvironmentStoreError",
    "Format",
    "InvalidKeyFileError",
    "KeyInput",
    "KeyMaterial",
    "KeyMode",
    "KeyModeMismatchError",
    "KeyRequiredError",
    "KeySourceError",
    "MergeOrder",
    "MigrationReport",
    "MissingExtraError",
    "NotEncryptedError",
    "NotFoundError",
    "Passphrase",
    "PlaintextNotAllowedError",
    "SchemaOutdatedError",
    "SchemaTooNewError",
    "Secret",
    "SetupMode",
    "SetupPrivilegeError",
    "Source",
    "StoreExistsError",
    "StoreInfo",
    "StoreNotFoundError",
    "UnsupportedFormatError",
    "ValidationError",
    "VariableExistsError",
    "VariableNotFoundError",
    "__version__",
    "generate_key_file",
    "generate_key_text",
    "load",
]


def __getattr__(name: str) -> object:
    """Resolve a public name on first use (PD 1).

    Args:
        name: The attribute.

    Returns:
        The public object.

    Raises:
        AttributeError: The name is not part of the public API.
    """
    module = _LAZY.get(name)
    if module is None:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    return getattr(importlib.import_module(module), name)


def __dir__() -> list[str]:
    """List the module attributes including the lazily resolved public API."""
    return sorted({*globals(), *__all__})
