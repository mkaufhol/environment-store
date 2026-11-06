"""`envs run`: run a command with the merged environment added to the current one (§6.13).

On POSIX the process is replaced (`execvpe`, D33), so the command's exit code is the exit code
of `run` and signals reach the command directly. Before that, the store is closed (no SQLite
handle or file lock leaks into the command) and stdout / stderr are flushed. A command that
cannot be started exits with the shell's codes, 127 or 126 (PD 28), on every platform.
"""

import subprocess  # nosec B404  # Windows has no exec(); used by run's fallback only
import sys
from typing import Final, NoReturn

import typer

from environment_store.cli._typer import passthrough_args
from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import (
    FirstWinsOpt,
    NestedPrefixOpt,
    OverwriteOpt,
    ReadKeysOpt,
    StoresArg,
)
from environment_store.cli.output import err
from environment_store.cli.state import get_state
from environment_store.core.errors import ValidationError

__all__ = ["run"]

_NOT_FOUND: Final = 127
_NOT_EXECUTABLE: Final = 126


def run(  # noqa: PLR0913 - the options of spec §6.13
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    overwrite: OverwriteOpt = False,
    nested: NestedPrefixOpt = False,
    first_wins: FirstWinsOpt = False,
    keys: ReadKeysOpt = None,
) -> None:
    """Run a command with the variables of stores.

    Usage: envs run [STORES]... -- CMD [ARGS]... The exit code is the command's. Variables
    already set are kept unless -o is given.
    """
    command = passthrough_args(ctx)
    if not command or not command[0]:
        # Checked before loading: a forgotten `--` or an empty program name (e.g. an unset
        # "$CMD") must not cost a key prompt (PD 28); exec would reject "" with a ValueError.
        message = "run needs a command after '--': envs run [STORES]... -- CMD [ARGS]..."
        raise ValidationError(message)
    state = get_state(ctx)
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    env = dict(state.runtime.environ())
    environment.apply(overwrite=overwrite, nested=nested, environ=env)
    state.close_stores()
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        if sys.platform == "win32":
            # S603 / B603: an argv list from the user's own command line, never a shell.
            completed = subprocess.run(command, env=env, check=False)  # noqa: S603  # nosec B603
            raise typer.Exit(completed.returncode)
        state.runtime.exec_process(command[0], command, env)
    except FileNotFoundError as error:
        _fail(command[0], error, _NOT_FOUND)
    except OSError as error:
        # PermissionError and the rest (e.g. ENOEXEC): found, but not executable.
        _fail(command[0], error, _NOT_EXECUTABLE)
    except ValueError as error:
        # The OS API refuses the argv itself (e.g. an embedded NUL byte): a usage error.
        message = f"cannot run '{command[0]}': {error}"
        raise ValidationError(message) from None


def _fail(file: str, error: OSError, code: int) -> NoReturn:
    err(f"Error: cannot run '{file}': {error.strerror}")
    raise typer.Exit(code) from None
