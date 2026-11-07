"""Key sources: reading existing secrets and choosing new ones (spec §4.3, §6.3, D3, D35, D53).

`SecretResolver` finds the secret of an existing store, in the order of D53: an explicit
source (file, stdin, or a key the caller already has) > `ENV_STORE_KEY_<STORE>` > the project
file's `[keys]` > a hidden prompt. `resolve_new_secret` produces the secret for a new
encryption and never looks at the environment (D53). Nothing is cached or stored (D3).
Messages name the source (a path, stdin or the variable), never the secret.
"""

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NoReturn, Protocol

from environment_store.config.prompt import Prompter
from environment_store.core.errors import (
    BackendError,
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.names import key_variable
from environment_store.core.secrets import Secret
from environment_store.crypto.keyfile import (
    generate_key,
    parse_key,
    passphrase_from_text,
    write_key_file,
)

__all__ = [
    "GenerateKeyFile",
    "KeyFile",
    "KeySource",
    "KeyStdin",
    "NewKeyFile",
    "NewPassphrase",
    "NewSecret",
    "NewSecretChoice",
    "SecretInput",
    "SecretResolver",
    "StoreInspector",
    "check_key_variables",
    "no_stdin",
    "read_secret_file",
    "resolve_new_secret",
    "secret_from_environment",
]

_STDIN: Final = "stdin"
_NEW_QUESTION: Final = "New passphrase: "


@dataclass(frozen=True, slots=True)
class KeyFile:
    """A key or passphrase file (`-k path`).

    Attributes:
        path: The file.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class KeyStdin:
    """The key or passphrase on stdin (`-k -`)."""


type KeySource = KeyFile | KeyStdin
"""Where an explicitly given secret is read from."""


class StoreInspector(Protocol):
    """What the resolver needs to know about a store; implemented by `EnvironmentStore`."""

    def store_info(self, name: str, /) -> StoreInfo:
        """Return the listing entry of a store.

        Args:
            name: The store name.

        Returns:
            The entry; raises `StoreNotFoundError` for a missing store.
        """
        ...

    def parse_secret(self, name: str, text: str, /) -> Secret:
        """Interpret raw secret text by the store's key mode.

        Args:
            name: The store name.
            text: The raw text.

        Returns:
            The secret.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SecretInput:
    """How secrets may be read in this invocation.

    Attributes:
        read_stdin: Claims stdin and reads all of it as bytes (PD 34).
        stdin_is_tty: Whether stdin is a terminal.
        prompter: Asks the user; `None` never prompts (non-interactive or `--noinput`, D35).
        environ: The environment variables, for `ENV_STORE_KEY_<STORE>` (D53); the edge
            passes `os.environ`. Never consulted for new secrets.
    """

    read_stdin: Callable[[], bytes]
    stdin_is_tty: bool
    prompter: Prompter | None
    environ: Mapping[str, str] = field(repr=False)


def no_stdin() -> NoReturn:
    """A `read_stdin` for callers that never read secrets from stdin.

    Raises:
        ValidationError: Always.
    """
    message = "reading a key or passphrase from stdin is not available here"
    raise ValidationError(message)


def read_secret_file(path: Path) -> str:
    """Read a key or passphrase file as strict UTF-8, unchanged.

    Args:
        path: The file.

    Returns:
        The text.

    Raises:
        KeySourceError: The path holds a NUL character, or the file cannot be read, is not
            UTF-8 or is empty (PD 3).
    """
    if "\0" in str(path):
        # The OS refuses such a path with a ValueError, not an OSError.
        message = f"key file path {str(path)!r} contains a NUL character"
        raise KeySourceError(message)
    what = f"key or passphrase file '{path}'"
    try:
        data = path.read_bytes()
    except OSError as err:
        message = f"cannot read {what}: {err.strerror}"
        raise KeySourceError(message) from err
    return _decode(data, what=what)


def _read_stdin(secret_input: SecretInput) -> str:
    return _decode(secret_input.read_stdin(), what=f"the key or passphrase on {_STDIN}")


def _decode(data: bytes, *, what: str) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        message = f"{what} is not valid UTF-8"
        # Not chained: the decode error holds the raw secret.
        raise KeySourceError(message) from None
    return _check_not_empty(text, what=what)


def _check_not_empty(text: str, *, what: str) -> str:
    # Empty after D3's stripping of exactly one trailing LF or CRLF, as passphrase_from_text.
    stripped = text[:-2] if text.endswith("\r\n") else text.removesuffix("\n")
    if not stripped:
        message = f"{what} is empty"
        raise KeySourceError(message)
    return text


def check_key_variables(
    stores: Iterable[str], *, explicit: Collection[str], environ: Mapping[str, str]
) -> None:
    """Refuse stores of one command that share a set key variable (D53).

    `my-app` and `my_app` both map to `ENV_STORE_KEY_MY_APP`, so it is unclear which store a
    set variable is meant for. That is no problem when an explicit key is given for every
    such store, because then the variable is not consulted; nor when it is not set.

    Args:
        stores: The stores of the command (repeats allowed).
        explicit: The stores that have an explicit key (`-k`, `key=`, `keys=`, `Source`).
        environ: The environment variables.

    Raises:
        ValidationError: Two or more stores map to one set variable and not all of them have
            an explicit key; the message names the stores and the variable, never its value.
    """
    by_variable: dict[str, list[str]] = {}
    for store in dict.fromkeys(stores):
        by_variable.setdefault(key_variable(store), []).append(store)
    for variable, names in by_variable.items():
        if len(names) > 1 and variable in environ and not set(names) <= set(explicit):
            listed = ", ".join(repr(name) for name in names)
            message = (
                f"stores {listed} all take their key from {variable}, so it is unclear which "
                "store it is for: unset it and give each of these stores its key explicitly"
            )
            raise ValidationError(message)


def secret_from_environment(
    inspector: StoreInspector, store: str, environ: Mapping[str, str]
) -> Secret | None:
    """Return an existing store's secret from `ENV_STORE_KEY_<STORE>`, if it gives one (D53).

    Args:
        inspector: Reads the store's metadata (only when the variable is set).
        store: The store name.
        environ: The environment variables.

    Returns:
        The secret, or `None` when the variable is not set or the store is plaintext (a
        variable for a plaintext store is ignored: environments are shared).

    Raises:
        StoreNotFoundError: The variable is set and the store does not exist.
        KeySourceError: The variable is set but empty, or not valid UTF-8.
        InvalidKeyFileError: A `keyfile` store and the value is not key text.
        KeyModeMismatchError: A `passphrase` store and the value is key text.
    """
    text = environ.get(key_variable(store))
    if text is None or not inspector.store_info(store).encrypted:
        return None
    return _parse_variable(inspector, store, text)


def _parse_variable(inspector: StoreInspector, store: str, text: str) -> Secret:
    variable = key_variable(store)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        message = f"{variable} is not valid UTF-8"
        # Not chained: the encode error holds the whole value.
        raise KeySourceError(message) from None
    _check_not_empty(text, what=f"{variable}, the key or passphrase of store {store!r},")
    try:
        return inspector.parse_secret(store, text)
    except (InvalidKeyFileError, KeyModeMismatchError) as error:
        # The parser's message names neither the source nor the value; name the variable.
        message = f"{variable} does not hold a usable key for store {store!r}: {error.detail}"
        raise type(error)(message, hint=error.hint) from error


class SecretResolver:
    """Finds the secret of an existing store (D3, D53).

    Explicit source > `ENV_STORE_KEY_<STORE>` > project key > prompt > `KeyRequiredError`.
    """

    _inspector: StoreInspector
    _input: SecretInput

    def __init__(self, inspector: StoreInspector, secret_input: SecretInput) -> None:
        """Create the resolver.

        Args:
            inspector: Reads store metadata and interprets secret text.
            secret_input: Stdin, terminal state and prompter of this invocation.
        """
        self._inspector = inspector
        self._input = secret_input

    def existing(
        self, store: str, source: KeySource | None, *, project_key: Path | None = None
    ) -> Secret | None:
        """Return the secret of an existing store, by the precedence of D53.

        Args:
            store: The store name.
            source: The explicitly given key source, or `None`.
            project_key: The project file's `[keys]` path for the store, or `None` (PD 5).

        Returns:
            The secret, or `None` for a plaintext store without a source or project key.

        Raises:
            StoreNotFoundError: The store does not exist (checked before reading or prompting).
            NotEncryptedError: A source or project key was given for a plaintext store.
            KeyRequiredError: The store is encrypted, nothing gives its key and prompting is
                off.
            KeySourceError: The source cannot be read, is not UTF-8 or is empty; or the key
                variable is set but empty.
            CryptoError: The text does not fit the store's key mode.
        """
        info = self._inspector.store_info(store)
        if not info.encrypted:
            if source is not None or project_key is not None:
                message = f"store {store!r} is not encrypted; it takes no key or passphrase"
                raise NotEncryptedError(message)
            return None
        if source is not None:
            return self._inspector.parse_secret(store, self._read(source))
        text = self._input.environ.get(key_variable(store))
        if text is not None:
            return _parse_variable(self._inspector, store, text)
        if project_key is not None:
            return self._inspector.parse_secret(store, read_secret_file(project_key))
        return self._inspector.parse_secret(store, self._prompt(store))

    def uses_key_variable(self, store: str, source: KeySource | None) -> bool:
        """Tell whether `existing` takes the store's secret from its key variable (D53).

        Args:
            store: The store name.
            source: The explicitly given key source, or `None`.

        Returns:
            Whether no source is given and `ENV_STORE_KEY_<STORE>` is set (it is still
            ignored for a plaintext store).
        """
        return source is None and key_variable(store) in self._input.environ

    def check_key_variables(self, stores: Iterable[str], *, explicit: Collection[str]) -> None:
        """`check_key_variables` with this invocation's environment.

        Args:
            stores: The stores of the command.
            explicit: The stores that have an explicit key.
        """
        check_key_variables(stores, explicit=explicit, environ=self._input.environ)

    def _read(self, source: KeySource) -> str:
        if isinstance(source, KeyFile):
            return read_secret_file(source.path)
        return _read_stdin(self._input)

    def _prompt(self, store: str) -> str:
        prompter = self._input.prompter
        if prompter is None:
            # Library wording; the CLI puts its -k hint in place of the hint (D47).
            raise KeyRequiredError.for_store(store)
        answer = prompter.secret(f"Key or passphrase for store {store!r}: ")
        return _check_not_empty(answer, what=f"the key or passphrase for store {store!r}")


@dataclass(frozen=True, slots=True)
class NewKeyFile:
    """Encrypt with an existing key file (`-k path`, `--new-key path`, `-` for stdin).

    Attributes:
        source: Where the key file text is read from.
    """

    source: KeySource


@dataclass(frozen=True, slots=True)
class GenerateKeyFile:
    """Generate a new key file (`--generate-key path`).

    Attributes:
        path: Where to create it (mode `0600`, never overwritten).
    """

    path: Path


@dataclass(frozen=True, slots=True)
class NewPassphrase:
    """Encrypt with a passphrase (`--passphrase`): piped on stdin or prompted twice."""


type NewSecretChoice = NewKeyFile | GenerateKeyFile | NewPassphrase
"""How the secret of a new encryption is chosen."""


@dataclass(frozen=True, slots=True, kw_only=True)
class NewSecret:
    """The secret of a new encryption.

    Attributes:
        secret: The key or passphrase.
        generated: The key file created for it, or `None`.
        from_stdin: Whether it was read from stdin, where nothing keeps it (D45).
    """

    secret: Secret = field(repr=False)
    generated: Path | None
    from_stdin: bool = False

    def discard(self) -> None:
        """Remove a generated key file; the caller decides when this is safe (PD 33).

        Raises:
            BackendError: The file exists but cannot be removed.
        """
        if self.generated is not None:
            try:
                self.generated.unlink(missing_ok=True)
            except OSError as err:
                message = f"cannot remove generated key file '{self.generated}': {err.strerror}"
                raise BackendError(message) from err


def resolve_new_secret(choice: NewSecretChoice, secret_input: SecretInput) -> NewSecret:
    """Produce the secret of a new encryption.

    Args:
        choice: Key file, generated key file or passphrase.
        secret_input: Stdin, terminal state and prompter of this invocation.

    Returns:
        The secret and, for a generated key file, its path.

    Raises:
        InvalidKeyFileError: A given key file is not a key file.
        KeySourceError: A key file or piped passphrase cannot be read, is not UTF-8 or is empty.
        KeyRequiredError: A passphrase on a terminal with prompting off (stdin is never read
            from a terminal, D35).
        ValidationError: A path for a generated key file exists already.
        BackendError: The generated key file cannot be written.
    """
    if isinstance(choice, NewKeyFile):
        if isinstance(choice.source, KeyFile):
            return NewSecret(secret=parse_key(read_secret_file(choice.source.path)), generated=None)
        text = _read_stdin(secret_input)
        return NewSecret(secret=parse_key(text), generated=None, from_stdin=True)
    if isinstance(choice, GenerateKeyFile):
        key = generate_key()
        write_key_file(choice.path, key)
        return NewSecret(secret=key, generated=choice.path)
    if not secret_input.stdin_is_tty:
        text = _read_stdin(secret_input)
        return NewSecret(secret=passphrase_from_text(text), generated=None, from_stdin=True)
    return NewSecret(secret=_prompt_new_passphrase(secret_input), generated=None)


def _prompt_new_passphrase(secret_input: SecretInput) -> Secret:
    if secret_input.prompter is None:
        message = (
            "a new passphrase is needed, but prompting is off: pipe it on stdin or drop --noinput"
        )
        raise KeyRequiredError(message)
    answer = secret_input.prompter.new_secret(_NEW_QUESTION)
    return passphrase_from_text(_check_not_empty(answer, what="the new passphrase"))
