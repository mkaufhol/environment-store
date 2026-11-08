"""`StoreSession`: everything the TUI does with stores, on the library facade.

The screens stay thin: they ask the session and show its results or its errors. Secrets live
only in the `OpenedStore` of the screen that shows the store and are never stored or cached
beyond it. Writes are refused when the store changed since it was shown, so a change made
elsewhere is never overwritten silently.
"""

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from environment_store.config.secrets import read_secret_file
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    EnvironmentStoreError,
    NotEncryptedError,
    StoreExistsError,
)
from environment_store.core.merge import MergeOrder
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import Secret
from environment_store.core.validation import validate_store_name
from environment_store.library.keys import generate_key_file
from environment_store.library.sources import Source
from environment_store.library.store import EnvironmentStore
from environment_store.tui.choices import ExportOptions, KeyFile, NewKey, TypedPassphrase
from environment_store.tui.messages import message_for

__all__ = ["OpenedStore", "ReadKeyFile", "StoreSession"]

type ReadKeyFile = Callable[[Path], str]
"""Reads a key or passphrase file as text (`config.secrets.read_secret_file`)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenedStore:
    """A store as the TUI shows it: its variables at one revision, and its secret.

    Attributes:
        name: The store name.
        secret: The store's key or passphrase; `None` for a plaintext store.
        revision: The revision the variables were read at.
        variables: The variables (read-only).
        from_environment: Whether the secret came from `ENV_STORE_KEY_<STORE>`.
    """

    name: str
    secret: Secret | None = field(repr=False)
    revision: int
    variables: Mapping[str, str] = field(repr=False)
    from_environment: bool = False

    def __post_init__(self) -> None:
        """Freeze the variables."""
        object.__setattr__(self, "variables", MappingProxyType(dict(self.variables)))


class StoreSession:
    """The library operations of the TUI over one `EnvironmentStore`."""

    _store: EnvironmentStore
    _key_paths: Mapping[str, Path]
    _project_file: Path | None
    _read_key_file: ReadKeyFile
    _ordered_overwrite: bool

    def __init__(
        self,
        store: EnvironmentStore,
        *,
        key_paths: Mapping[str, Path],
        project_file: Path | None = None,
        read_key_file: ReadKeyFile = read_secret_file,
        ordered_overwrite: bool = True,
    ) -> None:
        """Work on an open store.

        Args:
            store: The store; the caller closes it.
            key_paths: The project file's `[keys]`, tried before asking.
            project_file: The project file the keys come from, named in errors about them.
            read_key_file: Reads key and passphrase files.
            ordered_overwrite: The configured merge order: `True` for last wins.
        """
        self._store = store
        self._key_paths = MappingProxyType(dict(key_paths))
        self._project_file = project_file
        self._read_key_file = read_key_file
        self._ordered_overwrite = ordered_overwrite

    @property
    def ordered_overwrite(self) -> bool:
        """The configured merge order, the export dialog's default (`False`: first wins)."""
        return self._ordered_overwrite

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
        """Return a store's secret from `ENV_STORE_KEY_<STORE>`, tried first.

        Args:
            name: The store name.

        Returns:
            The secret, or `None` if the variable is not set or the store is plaintext.

        Raises:
            CryptoError: The variable is set but empty or does not fit the store's key mode.
        """
        return self._store.environment_secret(name)

    def secret_from_file(self, name: str, path: Path) -> Secret:
        """Read a key or passphrase file and interpret it by the store's key mode.

        Args:
            name: The store name.
            path: The file, used as given: `~` is already expanded by the caller (the unlock
                dialog's path input, or the project file's `[keys]`), since only the typed text
                tells a leading `~` from `./~`.

        Returns:
            The secret.

        Raises:
            KeySourceError: The file cannot be read or is empty.
            CryptoError: The text does not fit the store's key mode.
        """
        return self._store.parse_secret(name, self._read_key_file(path))

    def secret_from_text(self, name: str, text: str) -> Secret:
        """Interpret typed text (a passphrase) by the store's key mode.

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
                keys are bound by store name, so this is an error like in the CLI.
            CryptoError: The secret is missing or wrong.
        """
        info = self._store.store_info(name)
        self._check_project_key(info)
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
            ConcurrentModificationError: The store changed since it was shown.
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
            ConcurrentModificationError: The store changed since it was shown.
        """
        self._check_unchanged(opened)
        self._store.delete(opened.name, [name], key=opened.secret)
        return self.reload(opened)

    def create_store(self, name: str, key: NewKey | None) -> StoreInfo:
        """Create an empty store, like `create-store`.

        A generated key file is removed again when the store was not created, so a failure
        leaves nothing behind; it is kept when the store may already use it.

        Args:
            name: The new store's name.
            key: The new secret; `None` for a plaintext store.

        Returns:
            The new store's listing entry.

        Raises:
            ValidationError: An invalid name, or the path for a new key file exists already.
            StoreExistsError: The store exists already.
            CryptoError: An existing key file cannot be read or is no key file.
            BackendError: The store cannot be written; for a generated key file the message
                says that it was kept.
        """
        if key is None:
            return self._store.create_store(name)
        if isinstance(key, KeyFile):
            return self._store.create_store(name, encrypt=True, key=key.path)
        if isinstance(key, TypedPassphrase):
            return self._store.create_store(name, encrypt=True, key=key.passphrase)
        # Everything refusable is checked before the key file is written.
        validate_store_name(name)
        generate_key_file(key.path)
        try:
            return self._store.create_store(name, encrypt=True, key=key.path)
        except EnvironmentStoreError as error:
            if isinstance(error, StoreExistsError) or not self._exists(name):
                with suppress(OSError):
                    key.path.unlink(missing_ok=True)
                raise
            message = (
                f"{message_for(error)}; kept the generated key file '{key.path}': store "
                f"{name!r} may already be encrypted with it"
            )
            raise BackendError(message) from error

    def delete_store(self, name: str) -> None:
        """Delete a store and all its variables; needs no key.

        Args:
            name: The store name.
        """
        self._store.delete_store(name)

    def export(
        self, sources: Sequence[Source], path: Path, options: ExportOptions, *, force: bool
    ) -> None:
        """Export stores to a file with mode `0600`, in output order.

        The output order is the load order of the stores, sorted by name within a store; a
        variable in several stores keeps its first position and takes the merge order's value.

        Args:
            sources: The stores in load order with their secrets; an encrypted store without
                one takes its key from `ENV_STORE_KEY_<STORE>`.
            path: The output file.
            options: Format, nested and merge order.
            force: Replace an existing file.

        Raises:
            NotEncryptedError: The project file names a key for a plaintext store.
            OutputFileExistsError: The file exists and `force` is not set.
        """
        for source in sources:
            if source.key is None:
                self._check_project_key(self._store.store_info(source.name))
        order = MergeOrder.FIRST_WINS if options.first_wins else MergeOrder.LAST_WINS
        environment = self._store.load(sources, order=order)
        environment.to_file(path, fmt=options.fmt, nested=options.nested, force=force)

    def _exists(self, name: str) -> bool:
        try:
            return name in {info.name for info in self._store.list_stores()}
        except EnvironmentStoreError:
            return True  # unknown: the store may exist

    def _check_project_key(self, info: StoreInfo) -> None:
        # Keys are bound by store name, so a key for a plaintext store is an error.
        if not info.encrypted and info.name in self._key_paths:
            where = "the project file" if self._project_file is None else f"'{self._project_file}'"
            message = (
                f"[keys] in {where} names a key for store {info.name!r}, which is not "
                "encrypted: remove the entry"
            )
            raise NotEncryptedError(message)

    def _check_unchanged(self, opened: OpenedStore) -> None:
        if self._store.store_info(opened.name).revision != opened.revision:
            message = (
                f"store {opened.name!r} was changed elsewhere since it was read; nothing was "
                "written: reload it and try again"
            )
            raise ConcurrentModificationError(message)
