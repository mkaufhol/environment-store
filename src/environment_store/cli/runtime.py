"""`Runtime`: every terminal and OS boundary of the CLI in one injectable value.

Production code uses the defaults. Tests pass their own `Runtime` as the root context object
(`CliRunner.invoke(app, args, obj=Runtime(...))`), so TTY state, prompts, the process
replacement of `run`, the clock, the KDF cost and the adapters are faked without patching.
"""

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from environment_store.config.prompt import Prompter
from environment_store.core.clock import Clock, utc_now
from environment_store.core.models import KdfParams
from environment_store.library.store import AdapterOpener, open_configured_adapter

__all__ = ["ExecProcess", "Runtime", "environ", "stdin_is_tty", "stdout_is_tty"]

type ExecProcess = Callable[[str, list[str], Mapping[str, str]], NoReturn]
"""Replaces the process: `(file, argv, env)` like `os.execvpe`; argv is a list, as in typeshed."""


# Named functions rather than lambdas or bound methods: the streams are looked up at call time,
# so a replaced sys.stdin / sys.stdout (e.g. by CliRunner) is the one asked.
def environ() -> Mapping[str, str]:
    """Return the process environment."""
    return os.environ


def stdin_is_tty() -> bool:
    """Return whether the current stdin is a terminal."""
    return sys.stdin.isatty()


def stdout_is_tty() -> bool:
    """Return whether the current stdout is a terminal."""
    return sys.stdout.isatty()


@dataclass(frozen=True, slots=True, kw_only=True)
class Runtime:
    """The boundaries of one CLI invocation.

    Attributes:
        environ: Returns the environment variables (`ENV_STORE_*`, the base of `run`).
        cwd: Returns where the project file search starts.
        project_boundary: The last directory the project file search looks in; `None` for the
            filesystem root.
        uid: The owner a project file must have (PD 32); `None` for the effective user.
        stdin_is_tty: Whether stdin is a terminal (prompts, D3, D35).
        stdout_is_tty: Whether stdout is a terminal (`get` adds a newline only there, D33).
        prompter: Asks the user; `None` for a `TerminalPrompter`.
        exec_process: Replaces the process for `run` (D33).
        clock: Source of timestamps.
        kdf_params_factory: Argon2id parameters for new passphrases; `None` for the spec
            defaults (D34).
        adapter_opener: Opens adapters for connection strings.
    """

    environ: Callable[[], Mapping[str, str]] = environ
    cwd: Callable[[], Path] = Path.cwd
    project_boundary: Path | None = None
    uid: int | None = None
    stdin_is_tty: Callable[[], bool] = stdin_is_tty
    stdout_is_tty: Callable[[], bool] = stdout_is_tty
    prompter: Prompter | None = None
    exec_process: ExecProcess = os.execvpe
    clock: Clock = utc_now
    kdf_params_factory: Callable[[], KdfParams] | None = None
    adapter_opener: AdapterOpener = open_configured_adapter
