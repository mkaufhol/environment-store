"""`StoreSession`: everything the TUI does with stores, on the library facade (D31, PD 29).

The screens stay thin: they ask the session and show its results or its errors. Secrets live
only in the `OpenedStore` of the screen that shows the store and are never stored or cached
beyond it (D3). Writes are refused when the store changed since it was shown (D7), so a change
made elsewhere is never overwritten silently.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from environment_store.config.secrets import read_secret_file
from environment_store.core.errors import (
    ConcurrentModificationError,
    KeySourceError,
    NotEncryptedError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import Secret
from environment_store.library.store import EnvironmentStore

__all__ = ["OpenedStore", "ReadKeyFile", "StoreSession"]

type ReadKeyFile = Callable[[Path], str]
"""Reads a key or passphrase file as text (`config.secrets.read_secret_file`)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenedStore:
    """A store as the TUI shows it: its variables at one revision, and its secret.

    Attributes:
        name: The store name.
        secret: The store's key or passphrase; `None` for a plaintext store.
        revision: The revision the variables were read at (D7).
        variables: The variables (read-only).
    """

    name: str
    secret: Secret | None = field(repr=False)
    revision: int
    variables: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        """Freeze the variables."""
        object.__setattr__(self, "variables", MappingProxyType(dict(self.variables)))


class StoreSession:
    """The library operations of the TUI over one `EnvironmentStore`."""

    _store: EnvironmentStore
    _key_paths: Mapping[str, Path]
    _project_file: Path | None
    _read_key_file: ReadKeyFile

    def __init__(
        self,
        store: EnvironmentStore,
        *,
        key_paths: Mapping[str, Path],
        project_file: Path | None = None,
        read_key_file: ReadKeyFile = read_secret_file,
    ) -> None:
        """Work on an open store.

        Args:
            store: The store; the caller closes it.
            key_paths: The project file's `[keys]`, tried before asking (PD 5).
            project_file: The project file the keys come from, named in errors about them.
            read_key_file: Reads key and passphrase files.
        """
        self._store = store
        self._key_paths = MappingProxyType(dict(key_paths))
        self._project_file = project_file
        self._read_key_file = read_key_file

    def stores(self) -> list[StoreInfo]:
        """List every store; needs no key.

        Returns:
            The stores, sorted by name.
        """
        return self._store.list_stores()

    def project_key(self, name: str) -> Path | None:
        """Return the project file's key path for a store.

        Args:
            name: The store name.

        Returns:
            The path, or `None` if the project file names none.
        """
        return self._key_paths.get(name)

    def environment_secret(self, name: str) -> Secret | None:
        """Return a store's secret from `ENV_STORE_KEY_<STORE>`, tried first (D53).

        Args:
            name: The store name.

        Returns:
            The secret, or `None` if the variable is not set or the store is plaintext.

        Raises:
            CryptoError: The variable is set but empty or does not fit the store's key mode.
        """
        return self._store.environment_secret(name)

    def secret_from_file(self, name: str, path: Path) -> Secret:
        """Read a key or passphrase file and interpret it by the store's key mode (D3).

        Args:
            name: The store name.
            path: The file; `~` is expanded.

        Returns:
            The secret.

        Raises:
            KeySourceError: The file cannot be read or is empty.
            CryptoError: The text does not fit the store's key mode.
        """
        try:
            expanded = path.expanduser()
        except RuntimeError as err:
            message = f"key file path '{path}' names an unknown home directory"
            raise KeySourceError(message) from err
        return self._store.parse_secret(name, self._read_key_file(expanded))

    def secret_from_text(self, name: str, text: str) -> Secret:
        """Interpret typed text (a passphrase) by the store's key mode (D3).

        Args:
            name: The store name.
            text: The typed text.

        Returns:
            The secret.
        """
        return self._store.parse_secret(name, text)

    def open(self, name: str, secret: Secret | None = None) -> OpenedStore:
        """Read a store's variables.

        The revision is read first: if the store changes in between, the next write is refused
        as a conflict instead of overwriting the change.

        Args:
            name: The store name.
            secret: Its secret, if it is encrypted.

        Returns:
            The opened store.

        Raises:
            StoreNotFoundError: The store does not exist.
            NotEncryptedError: The store is plaintext but the project file names a key for it;
                keys are bound by store name, so this is an error like in the CLI (PD 5).
            CryptoError: The secret is missing or wrong.
        """
        info = self._store.store_info(name)
        if not info.encrypted and name in self._key_paths:
            where = "the project file" if self._project_file is None else f"'{self._project_file}'"
            message = (
                f"[keys] in {where} names a key for store {name!r}, which is not encrypted: "
                "remove the entry"
            )
            raise NotEncryptedError(message)
        revision = info.revision
        variables = self._store.variables(name, key=secret)
        return OpenedStore(name=name, secret=secret, revision=revision, variables=variables)

    def reload(self, opened: OpenedStore) -> OpenedStore:
        """Read a shown store again with its secret.

        Args:
            opened: The store as shown.

        Returns:
            The current state.
        """
        return self.open(opened.name, opened.secret)

    def set(self, opened: OpenedStore, name: str, value: str, *, overwrite: bool) -> OpenedStore:
        """Set one variable, unless the store changed since it was shown.

        Args:
            opened: The store as shown.
            name: The variable name.
            value: The value.
            overwrite: Replace the variable if it exists.

        Returns:
            The store after the write.

        Raises:
            ConcurrentModificationError: The store changed since it was shown (D7).
            VariableExistsError: The variable exists and `overwrite` is false.
        """
        self._check_unchanged(opened)
        self._store.set(opened.name, name, value, key=opened.secret, overwrite=overwrite)
        return self.reload(opened)

    def delete(self, opened: OpenedStore, name: str) -> OpenedStore:
        """Delete one variable, unless the store changed since it was shown.

        Args:
            opened: The store as shown.
            name: The variable name.

        Returns:
            The store after the write.

        Raises:
            ConcurrentModificationError: The store changed since it was shown (D7).
        """
        self._check_unchanged(opened)
        self._store.delete(opened.name, [name], key=opened.secret)
        return self.reload(opened)

    def _check_unchanged(self, opened: OpenedStore) -> None:
        if self._store.store_info(opened.name).revision != opened.revision:
            message = (
                f"store {opened.name!r} was changed elsewhere since it was read; nothing was "
                "written: reload it and try again"
            )
            raise ConcurrentModificationError(message)
