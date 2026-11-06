"""Exit codes of the CLI and the mapping from error categories (D24, spec §6)."""

from enum import IntEnum

from environment_store.core.errors import (
    AlreadyExistsError,
    ConcurrentModificationError,
    CryptoError,
    EnvironmentStoreError,
    NotFoundError,
)

__all__ = ["ExitCode", "exit_code_for"]


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
    """Return the exit code of an error by its category class (D24).

    Args:
        error: The error.

    Returns:
        The exit code.
    """
    for category, code in _CATEGORIES:
        if isinstance(error, category):
            return code
    return ExitCode.USAGE
