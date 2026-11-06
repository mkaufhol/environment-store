"""Key sources: reading existing secrets and choosing new ones (spec §4.3, §6.3, D3, D35).

`SecretResolver` turns a key source (file, stdin) or a prompt into the secret of an existing
store; `resolve_new_secret` produces the secret for a new encryption. Nothing is cached or
stored (D3). Messages name the source (a path or stdin), never the secret.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, NoReturn, Protocol

from environment_store.config.prompt import Prompter
from environment_store.core.errors import (
    BackendError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
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
    "no_stdin",
    "read_secret_file",
    "resolve_new_secret",
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
    """

    read_stdin: Callable[[], bytes]
    stdin_is_tty: bool
    prompter: Prompter | None


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


class SecretResolver:
    """Finds the secret of an existing store: explicit source, prompt or nothing (D3)."""

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

    def existing(self, store: str, source: KeySource | None) -> Secret | None:
        """Return the secret of an existing store.

        Args:
            store: The store name.
            source: The explicitly given key source, or `None`.

        Returns:
            The secret, or `None` for a plaintext store without a source.

        Raises:
            StoreNotFoundError: The store does not exist (checked before reading or prompting).
            NotEncryptedError: A source was given for a plaintext store.
            KeyRequiredError: The store is encrypted, no source was given and prompting is off.
            KeySourceError: The source cannot be read, is not UTF-8 or is empty.
            CryptoError: The text does not fit the store's key mode.
        """
        info = self._inspector.store_info(store)
        if not info.encrypted:
            if source is not None:
                message = f"store {store!r} is not encrypted; it takes no key or passphrase"
                raise NotEncryptedError(message)
            return None
        text = self._prompt(store) if source is None else self._read(source)
        return self._inspector.parse_secret(store, text)

    def _read(self, source: KeySource) -> str:
        if isinstance(source, KeyFile):
            return read_secret_file(source.path)
        return _read_stdin(self._input)

    def _prompt(self, store: str) -> str:
        prompter = self._input.prompter
        if prompter is None:
            message = (
                f"store {store!r} is encrypted and no key or passphrase was given: pass it "
                "with -k <path> (or -k - for stdin)"
            )
            raise KeyRequiredError(message)
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
