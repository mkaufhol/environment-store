"""`EnvironmentStore`: the public facade over one backend.

It owns exactly one adapter, opened on construction (so a refused schema or a missing extra
surfaces at once), and one `StoreService` over it. Keys are taken as `KeyInput`: for an
existing store a `Path` is read and interpreted by the store's mode; for a new secret a `Path`
must be a key file. Key text without a file is passed as `parse_key_text(text)`.

An existing store's key that is not given comes from the environment, `ENV_STORE_KEY_<STORE>` or
the load specification in `ENV_STORE_LOAD`; new keys never do. The environment is passed in
(`os.environ` by default) and never changed.
"""

import os
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Final, Literal, Self

from environment_store.config.key_variables import (
    check_key_variables,
    environment_key_source,
    secret_from_environment,
)
from environment_store.config.load_spec import LoadSpec
from environment_store.config.project import PROJECT_FILE_NAME
from environment_store.config.secrets import read_secret_file
from environment_store.config.settings import ENV_CONNECTION, Settings
from environment_store.core.adapter import Adapter, MigratableAdapter, MigrationReport, SetupMode
from environment_store.core.clock import Clock, utc_now
from environment_store.core.connection import open_adapter, scheme_of
from environment_store.core.errors import (
    ConfigurationError,
    ValidationError,
    VariableNotFoundError,
)
from environment_store.core.merge import MergeOrder
from environment_store.core.models import KdfParams, StoreInfo
from environment_store.core.models import Source as CoreSource
from environment_store.core.secrets import Secret
from environment_store.core.validation import validate_store_name, validate_variable_name
from environment_store.crypto.kdf import new_kdf_params
from environment_store.crypto.keyfile import parse_key
from environment_store.library.environment import Environment
from environment_store.library.sources import KeyInput, Source, check_key_input
from environment_store.service import Encryption, StoreService

__all__ = ["AdapterOpener", "EnvironmentStore", "open_configured_adapter"]

_MISSING_CONNECTION: Final = (
    f"no connection configured: pass connection=..., set {ENV_CONNECTION}, or set "
    f"'connection' in {PROJECT_FILE_NAME}"
)

type AdapterOpener = Callable[[str, SetupMode], Adapter]
"""Opens the adapter for a connection string; the test seam of `EnvironmentStore`."""


def open_configured_adapter(connection: str, setup: SetupMode) -> Adapter:
    """Open an adapter through the scheme registry (`core.connection.open_adapter`).

    Args:
        connection: The connection string.
        setup: How to treat the database layout on open.

    Returns:
        The open adapter.
    """
    return open_adapter(connection, setup=setup)


class EnvironmentStore:
    """Stores and variables of one backend, the library's entry point.

    Use it as a context manager, or call `close()`; every method after `close()` raises
    `ValidationError`.
    """

    _scheme: str
    _service: StoreService
    _environ: Mapping[str, str]
    _closed: bool

    def __init__(  # noqa: PLR0913 - every boundary is a keyword
        self,
        connection: str,
        *,
        setup: SetupMode = SetupMode.AUTO,
        clock: Clock = utc_now,
        kdf_params_factory: Callable[[], KdfParams] | None = None,
        opener: AdapterOpener = open_configured_adapter,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Open the backend a connection string names.

        Args:
            connection: E.g. `sqlite:///envs.db`, `json://envs` or `postgresql://host/db`.
            setup: How SQL backends treat their schema on open.
            clock: Source of timestamps.
            kdf_params_factory: Argon2id parameters for new passphrases; `None` for the
                defaults (`t=3`, `m=64 MiB`, `p=4`, as RFC 9106 recommends).
            opener: Opens the adapter; tests inject fakes here.
            environ: Where `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD` are looked up; `None`
                for `os.environ`.

        Raises:
            ValidationError: The connection string is malformed or its scheme is unknown.
            MissingExtraError: The backend needs an optional extra.
            BackendError: The backend cannot be opened or its schema is refused.
        """
        self._scheme = scheme_of(connection)
        self._environ = os.environ if environ is None else environ
        adapter = opener(connection, setup)
        self._service = StoreService(
            adapter,
            clock=clock,
            kdf_params_factory=new_kdf_params if kdf_params_factory is None else kdf_params_factory,
        )
        self._closed = False

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        setup: SetupMode = SetupMode.AUTO,
        clock: Clock = utc_now,
        kdf_params_factory: Callable[[], KdfParams] | None = None,
        opener: AdapterOpener = open_configured_adapter,
    ) -> Self:
        """Open the backend named by `ENV_STORE_CONNECTION` only (no project file).

        Args:
            environ: The environment, also for `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD`;
                `None` for `os.environ`.
            setup: As for the constructor.
            clock: As for the constructor.
            kdf_params_factory: As for the constructor.
            opener: As for the constructor.

        Returns:
            The open store.

        Raises:
            ConfigurationError: The variable is not set or empty.
        """
        environ = os.environ if environ is None else environ
        connection = environ.get(ENV_CONNECTION)
        if not connection:
            message = f"no connection configured: set {ENV_CONNECTION}"
            raise ConfigurationError(message)
        return cls(
            connection,
            setup=setup,
            clock=clock,
            kdf_params_factory=kdf_params_factory,
            opener=opener,
            environ=environ,
        )

    @classmethod
    def from_settings(  # noqa: PLR0913 - every boundary is a keyword
        cls,
        settings: Settings,
        *,
        setup: SetupMode = SetupMode.AUTO,
        clock: Clock = utc_now,
        kdf_params_factory: Callable[[], KdfParams] | None = None,
        opener: AdapterOpener = open_configured_adapter,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Open the backend of resolved settings (option > environment > project file).

        Args:
            settings: The resolved settings.
            setup: As for the constructor.
            clock: As for the constructor.
            kdf_params_factory: As for the constructor.
            opener: As for the constructor.
            environ: As for the constructor.

        Returns:
            The open store.

        Raises:
            ConfigurationError: No connection is configured.
        """
        if settings.connection is None:
            raise ConfigurationError(_MISSING_CONNECTION)
        return cls(
            settings.connection,
            setup=setup,
            clock=clock,
            kdf_params_factory=kdf_params_factory,
            opener=opener,
            environ=environ,
        )

    # --- lifetime ------------------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        """Whether `close()` was called."""
        return self._closed

    def close(self) -> None:
        """Close the backend; idempotent."""
        if not self._closed:
            self._closed = True
            self._service.adapter.close()

    def __enter__(self) -> Self:
        """Return the store itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the store; never suppresses an exception."""
        self.close()

    def __repr__(self) -> str:
        """Show the scheme, never the connection string (it may hold a password)."""
        return f"EnvironmentStore(scheme={self._scheme!r})"

    # --- stores --------------------------------------------------------------------------------

    def list_stores(self) -> list[StoreInfo]:
        """List every store; needs no key.

        Returns:
            One entry per store, sorted by name.
        """
        return self._open_service().list_stores()

    def store_info(self, name: str) -> StoreInfo:
        """Return the listing entry of one store; needs no key.

        Args:
            name: The store name.

        Returns:
            The entry.

        Raises:
            StoreNotFoundError: The store does not exist.
        """
        validate_store_name(name)
        return self._open_service().adapter.read_store(name).info

    def create_store(
        self, name: str, *, encrypt: bool = False, key: KeyInput | None = None
    ) -> StoreInfo:
        """Create an empty store.

        Args:
            name: The new store's name.
            encrypt: Create an encrypted store; needs `key`.
            key: The new secret: a key file `Path`, a `KeyMaterial` or a `Passphrase`.

        Returns:
            The new store's listing entry.

        Raises:
            ValidationError: `encrypt` without `key`, `key` without `encrypt`, or invalid input.
            StoreExistsError: The store exists already.
        """
        service = self._open_service()
        if encrypt and key is None:
            message = (
                "an encrypted store needs a key: pass key=Path(...), KeyMaterial or Passphrase"
            )
            raise ValidationError(message)
        if key is not None and not encrypt:
            message = "a key is only used for an encrypted store: pass encrypt=True"
            raise ValidationError(message)
        secret = None if key is None else _new_secret(key)
        return service.create_store(name, secret=secret)

    def delete_store(self, name: str) -> None:
        """Delete a store; needs no key.

        Args:
            name: The store name.
        """
        self._open_service().delete_store(name)

    def copy_store(
        self,
        src: str,
        dst: str,
        *,
        key: KeyInput | None = None,
        encryption: Literal["same", "plain"] | KeyInput = "same",
        to: "EnvironmentStore | None" = None,
    ) -> StoreInfo:
        """Copy a store under a new name or into another backend.

        Args:
            src: The source store.
            dst: The new store.
            key: The source's key, if it is encrypted.
            encryption: `"same"`, `"plain"` or a new secret for the copy.
            to: The target backend; `None` for this one.

        Returns:
            The new store's listing entry.
        """
        service, secret, chosen, destination = self._copy_arguments(src, key, encryption, to)
        return service.copy_store(
            src, dst, secret=secret, encryption=chosen, destination=destination
        )

    def move_store(
        self,
        src: str,
        dst: str,
        *,
        key: KeyInput | None = None,
        encryption: Literal["same", "plain"] | KeyInput = "same",
        to: "EnvironmentStore | None" = None,
    ) -> StoreInfo:
        """Copy a store, then delete the source; a failure never leaves zero copies.

        Arguments as for `copy_store`.

        Returns:
            The new store's listing entry.
        """
        service, secret, chosen, destination = self._copy_arguments(src, key, encryption, to)
        return service.move_store(
            src, dst, secret=secret, encryption=chosen, destination=destination
        )

    # --- variables -----------------------------------------------------------------------------

    def variables(self, store: str, *, key: KeyInput | None = None) -> dict[str, str]:
        """Read all variables of a store.

        Args:
            store: The store name.
            key: Its key, if it is encrypted.

        Returns:
            The variables, sorted by name.
        """
        service = self._open_service()
        return service.read_variables(store, secret=self._existing_secret(store, key))

    def get(self, store: str, name: str, *, key: KeyInput | None = None) -> str:
        """Read one variable.

        Args:
            store: The store name.
            name: The variable name.
            key: The store's key, if it is encrypted.

        Returns:
            The value.

        Raises:
            VariableNotFoundError: The variable does not exist.
        """
        validate_variable_name(name)
        variables = self.variables(store, key=key)
        if name not in variables:
            raise VariableNotFoundError([name], store=store)
        return variables[name]

    def set(
        self,
        store: str,
        name: str,
        value: str,
        *,
        key: KeyInput | None = None,
        overwrite: bool = False,
    ) -> None:
        """Set one variable.

        Args:
            store: The store name.
            name: The variable name.
            value: The value.
            key: The store's key, if it is encrypted.
            overwrite: Replace the variable if it exists.
        """
        self.set_many(store, {name: value}, key=key, overwrite=overwrite)

    def set_many(
        self,
        store: str,
        values: Mapping[str, str],
        *,
        key: KeyInput | None = None,
        overwrite: bool = False,
    ) -> None:
        """Set several variables in one write.

        Args:
            store: The store name.
            values: The variables.
            key: The store's key, if it is encrypted.
            overwrite: Replace variables that exist.
        """
        service = self._open_service()
        secret = self._existing_secret(store, key)
        service.set_variables(store, values, secret=secret, overwrite=overwrite)

    def delete(self, store: str, names: Collection[str], *, key: KeyInput | None = None) -> None:
        """Delete variables in one write.

        Args:
            store: The store name.
            names: The variable names.
            key: The store's key, if it is encrypted.
        """
        service = self._open_service()
        service.delete_variables(store, names, secret=self._existing_secret(store, key))

    # --- encryption ----------------------------------------------------------------------------

    def encrypt_store(self, store: str, *, key: KeyInput) -> None:
        """Encrypt a plaintext store; there is no way back.

        A plaintext copy is made with `copy_store(..., encryption="plain")`.

        Args:
            store: The store name.
            key: The new secret (a key file `Path`, `KeyMaterial` or `Passphrase`).
        """
        self._open_service().encrypt_store(store, secret=_new_secret(key))

    def rekey_store(self, store: str, *, old: KeyInput | None = None, new: KeyInput) -> None:
        """Re-encrypt a store with a new secret.

        Args:
            store: The store name.
            old: The current key; `None` takes it from `ENV_STORE_KEY_<STORE>`.
            new: The new secret (a key file `Path`, `KeyMaterial` or `Passphrase`); never
                taken from the environment.
        """
        service = self._open_service()
        old_secret = self._existing_secret(store, old)
        service.rekey_store(store, old=old_secret, new=_new_secret(new))

    def secret_for(self, store: str, key: KeyInput) -> Secret:
        """Turn a key input into the secret of an existing store.

        Args:
            store: The store name.
            key: A `Path` (read and interpreted by the store's mode), `KeyMaterial` or
                `Passphrase` (returned as is).

        Returns:
            The secret.
        """
        self._open_service()
        checked = check_key_input(key)
        if isinstance(checked, Path):
            return self.parse_secret(store, read_secret_file(checked))
        return checked

    def environment_secret(self, store: str) -> Secret | None:
        """Return an existing store's secret from `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD`.

        The frontends use it to try the environment before a project key or a prompt.

        Args:
            store: The store name.

        Returns:
            The secret, or `None` if neither variable has a key for the store or the store is
            plaintext.

        Raises:
            ValidationError: Both variables have a key for the store.
            ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
            KeySourceError: The key variable is set but empty or not UTF-8.
            CryptoError: The value does not fit the store's key mode; it names the variable,
                never the value.
        """
        self._open_service()
        validate_store_name(store)
        return secret_from_environment(self, store, self._environ)

    def environment_key_source(self, store: str) -> str | None:
        """Name the environment variable that gives a store's key, without reading the store.

        Args:
            store: The store name.

        Returns:
            `ENV_STORE_KEY_<STORE>` when it is set, else `ENV_STORE_LOAD` when it has a key
            for the store, else `None`. A plaintext store ignores either.

        Raises:
            ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
        """
        self._open_service()
        validate_store_name(store)
        return environment_key_source(store, self._environ)

    def parse_secret(self, store: str, text: str) -> Secret:
        """Interpret raw secret text by the store's key mode.

        Args:
            store: The store name.
            text: The text of a key file or a passphrase.

        Returns:
            The secret.
        """
        return self._open_service().parse_secret(store, text)

    # --- loading, schema -----------------------------------------------------------------------

    def load(
        self, sources: Sequence[Source | str], *, order: MergeOrder = MergeOrder.LAST_WINS
    ) -> Environment:
        """Read stores in load order for merging.

        Args:
            sources: Store names or `Source`s with keys, in load order.
            order: Which store wins for a variable present in several stores.

        Returns:
            The loaded stores.
        """
        resolved = self._resolved_sources(sources)
        return Environment(stores=tuple(self._open_service().load(resolved)), order=order)

    def load_spec(self, sources: Sequence[Source | str]) -> LoadSpec:
        """Build the load specification for `ENV_STORE_LOAD`, proving every key.

        Keys are resolved as for `load`; every store is decrypted, so a wrong key fails here and
        not in the deployment.

        Args:
            sources: Store names or `Source`s with keys, in load order.

        Returns:
            The specification: the stores in order and the secret of every encrypted one.
            `encode()` gives the value of `ENV_STORE_LOAD`.

        Raises:
            ValidationError: No stores, or a single string instead of a list.
            KeyRequiredError: An encrypted store has no key.
            DecryptionError: A key does not open its store.
            NotEncryptedError: A key was given for a plaintext store.
        """
        resolved = self._resolved_sources(sources)
        self._open_service().load(resolved)
        return LoadSpec(
            stores=tuple(source.name for source in resolved),
            keys={source.name: source.secret for source in resolved if source.secret is not None},
        )

    def migrate(self) -> MigrationReport:
        """Create or upgrade the schema of a SQL backend.

        Returns:
            What was done.

        Raises:
            ValidationError: The backend has no schema (file backends); a silent success
                would hide a wrong connection string.
        """
        adapter = self._open_service().adapter
        if not isinstance(adapter, MigratableAdapter):
            message = f"the {self._scheme!r} backend has no schema to migrate"
            raise ValidationError(message)
        return adapter.migrate()

    # --- helpers -------------------------------------------------------------------------------

    def _open_service(self) -> StoreService:
        if self._closed:
            message = "this EnvironmentStore is closed"
            raise ValidationError(message)
        return self._service

    def _existing_secret(self, store: str, key: KeyInput | None) -> Secret | None:
        # The explicit key, else the environment; None lets the service raise
        # KeyRequiredError for an encrypted store.
        return self.environment_secret(store) if key is None else self.secret_for(store, key)

    def _resolved_sources(self, sources: Sequence[Source | str]) -> list[CoreSource]:
        self._open_service()
        if isinstance(sources, str):
            message = "sources must be a list of stores, not a single string"
            raise ValidationError(message)
        checked = [_checked_source(source) for source in sources]
        # Before any key is read: a shared key variable is ambiguous.
        check_key_variables(
            self,
            [source.name for source in checked],
            explicit={source.name for source in checked if source.key is not None},
            environ=self._environ,
        )
        return [self._core_source(source) for source in checked]

    def _core_source(self, source: Source) -> CoreSource:
        return CoreSource(name=source.name, secret=self._existing_secret(source.name, source.key))

    def _copy_arguments(
        self,
        src: str,
        key: KeyInput | None,
        encryption: Literal["same", "plain"] | KeyInput,
        to: "EnvironmentStore | None",
    ) -> tuple[StoreService, Secret | None, Encryption, StoreService | None]:
        service = self._open_service()
        destination = None if to is None else to._open_service()
        return service, self._existing_secret(src, key), _encryption(encryption), destination


def _checked_source(source: Source | str) -> Source:
    if isinstance(source, str):
        return Source(source)
    if not isinstance(source, Source):
        message = f"a load source must be a Source or a store name, got {type(source).__name__}"
        raise ValidationError(message)
    return source


def _new_secret(key: KeyInput) -> Secret:
    checked = check_key_input(key)
    if isinstance(checked, Path):
        return parse_key(read_secret_file(checked))
    return checked


def _encryption(encryption: Literal["same", "plain"] | KeyInput) -> Encryption:
    if isinstance(encryption, str):
        if encryption not in {"same", "plain"}:
            message = (
                "encryption must be 'same', 'plain', a key file Path, KeyMaterial or Passphrase"
            )
            raise ValidationError(message)
        return encryption
    return _new_secret(encryption)
