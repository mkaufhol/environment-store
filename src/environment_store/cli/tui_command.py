"""`envs tui`: start the terminal user interface (spec §6.14, D15, PD 29, PD 31).

The settings are resolved like for every command (`EnvsCommand`: connection, project file
`[keys]`). The TUI is interactive, so `--noinput` and a stdin or stdout that is not a terminal
are refused. The `tui` package is imported only inside the command: the one recorded `cli → tui`
edge (PD 31); without textual it raises `MissingExtraError` (exit 1 with the install hint).
"""

import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.state import get_state
from environment_store.core.errors import ValidationError

__all__ = ["register", "tui"]


def register(app: typer.Typer) -> None:
    """Register `tui` on the app.

    Args:
        app: The `envs` app.
    """
    app.command("tui", cls=EnvsCommand)(tui)


def tui(ctx: typer.Context) -> None:
    """Start the TUI: browse stores, view, add, edit and delete variables (needs the tui extra)."""
    state = get_state(ctx)
    if state.noinput:
        message = "envs tui is interactive and cannot run with --noinput"
        raise ValidationError(message)
    runtime = state.runtime
    if not (runtime.stdin_is_tty() and runtime.stdout_is_tty()):
        message = "envs tui needs a terminal: stdin and stdout must not be redirected"
        raise ValidationError(message)
    from environment_store.tui import run_tui  # noqa: PLC0415 - optional extra, imported only when "envs tui" runs

    store = state.open_store(ctx)
    run_tui(store, key_paths=state.settings().key_paths)
