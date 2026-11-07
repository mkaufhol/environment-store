"""Secrets for commands: an existing store's key, a new secret, generated key files (D3, PD 33).

- `existing_secret`: `-k path|-` > `ENV_STORE_KEY_<STORE>` (D53) > the project file's
  `[keys]` (PD 5) > a prompt when interactive > `KeyRequiredError` (exit 4).
- `new_secret`: exactly one of the new-key option, `--generate-key` and `--passphrase`
  (PD 24); `--generate-key -` is refused for every command. `new_secret_choice` checks the
  options alone, so a command can refuse them before it asks for an existing key.
- `keep_or_discard`: wraps the writing library call; after success it warns about a new secret
  read from stdin (D45), after a failure it removes a generated key file only when the store
  provably does not use it (PD 33).
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import typer

from environment_store.cli.key_options import parse_key_path, parse_writing_key
from environment_store.cli.output import err
from environment_store.cli.state import CliState, get_state
from environment_store.config.secrets import (
    GenerateKeyFile,
    KeySource,
    NewKeyFile,
    NewPassphrase,
    NewSecret,
    NewSecretChoice,
    SecretResolver,
    resolve_new_secret,
)
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    ConfigurationError,
    CryptoError,
    EnvironmentStoreError,
    KeyModeMismatchError,
    NotEncryptedError,
    NotFoundError,
    StoreExistsError,
    ValidationError,
    VariableExistsError,
)
from environment_store.core.secrets import KeyMaterial, Secret
from environment_store.library.store import EnvironmentStore

__all__ = [
    "existing_secret",
    "keep_or_discard",
    "new_secret",
    "new_secret_choice",
    "resolve_existing",
]

_STDIN_PATH: Final = Path("-")
# An empty --generate-key value arrives as Path(""), which is Path(".").
_NO_FILE_PATH: Final = Path()
# Raised before anything is written (PD 33). AlreadyExistsError is narrowed per command below.
_BEFORE_WRITE: Final = (
    ValidationError,
    ConfigurationError,
    NotFoundError,
    CryptoError,
    ConcurrentModificationError,
    VariableExistsError,
    StoreExistsError,
)


def existing_secret(ctx: typer.Context, store: str, key: str | None) -> Secret | None:
    """Return the secret of an existing store for a writing command.

    Args:
        ctx: The command's context; the store is opened through `CliState.open_store`.
        store: The store name.
        key: The `-k` value (a path or `-`), or `None`.

    Returns:
        The secret, or `None` for a plaintext store without a key.

    Raises:
        StoreNotFoundError: The store does not exist (checked before reading or prompting).
        NotEncryptedError: A key (given or from `[keys]`) for a plaintext store.
        KeyRequiredError: No key and no prompt allowed (exit 4, hint `-k`).
        CryptoError: The key cannot be read or does not fit the store.
    """
    state = get_state(ctx)
    environment = state.open_store(ctx)
    resolver = SecretResolver(environment, state.secret_input("-k -"))
    return resolve_existing(state, resolver, store, parse_writing_key(key))


def resolve_existing(
    state: CliState, resolver: SecretResolver, store: str, source: KeySource | None
) -> Secret | None:
    """Resolve one store's secret by the precedence of `SecretResolver.existing` (D53).

    Args:
        state: The invocation state (for the project file's `[keys]`).
        resolver: The resolver over the open store.
        store: The store name.
        source: The source given on the command line, or `None`.

    Returns:
        The secret, or `None` for a plaintext store.

    Raises:
        NotEncryptedError: A project key for a plaintext store names the project file (PD 5).
        KeyModeMismatchError: A key file for a passphrase store, with what to do instead.
    """
    try:
        return _resolve_existing(state, resolver, store, source)
    except KeyModeMismatchError as error:
        if resolver.uses_key_variable(store, source):
            # The message names the variable; -k is not what the user gave (D53).
            raise
        message = (
            f"{error}: pass the passphrase file with -k (or -k - for stdin), or switch the "
            f"store to the key file with 'envs rekey -s {store} --new-key <path>'"
        )
        raise KeyModeMismatchError(message) from error


def _resolve_existing(
    state: CliState, resolver: SecretResolver, store: str, source: KeySource | None
) -> Secret | None:
    if source is not None:
        return resolver.existing(store, source)
    settings = state.settings()
    path = settings.key_paths.get(store)
    if path is None:
        return resolver.existing(store, None)
    try:
        return resolver.existing(store, None, project_key=path)
    except NotEncryptedError as error:
        message = (
            f"[keys] in '{settings.project_file}' names a key for store {store!r}, which is not "
            "encrypted: remove the entry"
        )
        raise NotEncryptedError(message) from error


def new_secret(
    ctx: typer.Context,
    *,
    key: str | None,
    generate: Path | None,
    passphrase: bool,
    key_option: str,
) -> NewSecret | None:
    """Return the secret of a new encryption, or `None` if no new-secret option was given.

    Args:
        ctx: The command's context.
        key: The existing key file option (`--new-key`, or `-k` for `create-store`).
        generate: The `--generate-key` path.
        passphrase: Whether `--passphrase` was given.
        key_option: How the command calls the key file option, for messages.

    Returns:
        The new secret, or `None`.

    Raises:
        ValidationError: More than one option, `--generate-key -` (PD 24), or an empty path.
    """
    choice = new_secret_choice(
        key=key, generate=generate, passphrase=passphrase, key_option=key_option
    )
    if choice is None:
        return None
    purpose = f"{key_option} -" if isinstance(choice, NewKeyFile) else "--passphrase"
    return resolve_new_secret(choice, get_state(ctx).secret_input(purpose))


def new_secret_choice(
    *, key: str | None, generate: Path | None, passphrase: bool, key_option: str
) -> NewSecretChoice | None:
    """Check the new-secret options and return the choice they make; nothing is read.

    Args:
        key: The existing key file option (`--new-key`, or `-k` for `create-store`).
        generate: The `--generate-key` path.
        passphrase: Whether `--passphrase` was given.
        key_option: How the command calls the key file option, for messages.

    Returns:
        The choice, or `None` if no new-secret option was given.

    Raises:
        ValidationError: More than one option, `--generate-key -` (PD 24), or an empty path.
    """
    given = sum((key is not None, generate is not None, passphrase))
    if given > 1:
        message = f"use only one of {key_option}, --generate-key, --passphrase"
        raise ValidationError(message)
    if generate == _STDIN_PATH:
        message = (
            "--generate-key needs a file path; to print a new key use 'envs keygen -' and "
            f"pass it with '{key_option} -'"
        )
        raise ValidationError(message)
    if generate == _NO_FILE_PATH:
        message = "--generate-key needs a file path"
        raise ValidationError(message)
    if key is not None:
        return NewKeyFile(parse_key_path(key, option=key_option))
    if generate is not None:
        return GenerateKeyFile(generate)
    return NewPassphrase() if passphrase else None


@contextmanager
def keep_or_discard(
    new: NewSecret | None, *, target: str, store: EnvironmentStore, creates_target: bool
) -> Generator[None]:
    """Remove a generated key file after a failure only if the store cannot use it (PD 33).

    After success, a secret read from stdin is kept nowhere by envs, so a warning names the
    store that cannot be read again without it (D45).

    Args:
        new: The new secret, or `None` (then nothing happens).
        target: The store that is encrypted with it.
        store: The backend of `target`, to check whether it exists after a failure.
        creates_target: Whether the command creates `target` (`create-store`, `cp-store`,
            `mv-store`).

    Yields:
        Nothing; the exception of the wrapped block is always re-raised.
    """
    try:
        yield
    except BaseException as error:
        if new is not None and new.generated is not None:
            _after_failure(new, new.generated, error, target, store, creates_target=creates_target)
        raise
    if new is not None and new.from_stdin:
        # Only once the store is written: a failed command encrypts nothing with it (D45).
        what = "key" if isinstance(new.secret, KeyMaterial) else "passphrase"
        err(
            f"Warning: envs does not save this {what}; keep it, or store '{target}' cannot be "
            "read again"
        )


def _after_failure(  # noqa: PLR0913 - the failure and everything needed to judge it
    new: NewSecret,
    path: Path,
    error: BaseException,
    target: str,
    store: EnvironmentStore,
    *,
    creates_target: bool,
) -> None:
    if not _unused(error, target, store, creates_target=creates_target):
        err(f"kept generated key file '{path}'; store '{target}' may already be encrypted with it")
        return
    try:
        new.discard()
    except BackendError as failure:
        err(str(failure))


def _unused(
    error: BaseException, target: str, store: EnvironmentStore, *, creates_target: bool
) -> bool:
    # A BackendError or a non-library exception may come after a commit: keep the key.
    if not isinstance(error, _BEFORE_WRITE):
        return False
    if not creates_target or isinstance(error, StoreExistsError):
        return True
    try:
        return target not in {info.name for info in store.list_stores()}
    except EnvironmentStoreError:
        return False
