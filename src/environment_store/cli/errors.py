"""Exit codes and messages of the CLI: the mapping from library errors.

Library errors name library parameters (`overwrite=True`, `force=True`, `fmt=`, `key=`,
`nested=True`) in their `hint`; the CLI shows the error's `detail` with its own option in their
place.
"""

from enum import IntEnum
from typing import Final

from environment_store.core.errors import (
    AlreadyExistsError,
    ConcurrentModificationError,
    CryptoError,
    EnvironmentStoreError,
    InvalidKeyFileError,
    KeyRequiredError,
    NotFoundError,
    VariableExistsError,
)
from environment_store.core.names import key_variable
from environment_store.formats import NestedInputError
from environment_store.formats.dotenv import DotenvValueError
from environment_store.library.files import OutputFileExistsError

__all__ = ["ExitCode", "exit_code_for", "message_for"]


class ExitCode(IntEnum):
    """The exit codes of every command except `run`, which passes its command's code through."""

    OK = 0
    USAGE = 1
    NOT_FOUND = 2
    EXISTS = 3
    KEY = 4
    CONFLICT = 5


# Checked in order; anything else (validation, configuration, missing extra, backend) is 1.
_CATEGORIES: tuple[tuple[type[EnvironmentStoreError], ExitCode], ...] = (
    (NotFoundError, ExitCode.NOT_FOUND),
    (AlreadyExistsError, ExitCode.EXISTS),
    (CryptoError, ExitCode.KEY),
    (ConcurrentModificationError, ExitCode.CONFLICT),
)


def exit_code_for(error: EnvironmentStoreError) -> ExitCode:
    """Return the exit code of an error by its category class.

    Args:
        error: The error.

    Returns:
        The exit code.
    """
    for category, code in _CATEGORIES:
        if isinstance(error, category):
            return code
    return ExitCode.USAGE


_KEY_HINT: Final = "pass it with -k <path> (or -k - for stdin)"

# Error class -> the CLI's remedy, replacing the library's hint. Checked in order.
_CLI_HINTS: Final[tuple[tuple[type[EnvironmentStoreError], str], ...]] = (
    (VariableExistsError, "use -o/--overwrite to replace them"),
    (OutputFileExistsError, "use --force to replace it"),
    (DotenvValueError, "export with -t json or -t toml, or use envs run instead"),
    (
        NestedInputError,
        "nested input (e.g. a --nested export) is refused, import a flat object of string values "
        "instead",
    ),
    (InvalidKeyFileError, "create one with envs keygen"),
    (KeyRequiredError, _KEY_HINT),
)


def message_for(error: EnvironmentStoreError) -> str:
    """Return the message the CLI prints for a library error.

    An error that carries a library hint and has a CLI remedy shows its detail with the CLI's
    option instead; every other error keeps its message.

    Args:
        error: The error.

    Returns:
        The message, without the `Error: ` prefix.
    """
    if isinstance(error, KeyRequiredError) and error.store is not None:
        # The store's key variable is a source of the CLI as well.
        return f"{error.detail}; {_KEY_HINT}, or set {key_variable(error.store)}"
    if error.hint is not None:
        for category, hint in _CLI_HINTS:
            if isinstance(error, category):
                return f"{error.detail}; {hint}"
    return str(error)
