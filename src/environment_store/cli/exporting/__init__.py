"""The export, export-shell, export-credentials and run commands."""

import typer

from environment_store.cli._typer import EnvsCommand, PassthroughCommand
from environment_store.cli.exporting.credentials import export_credentials
from environment_store.cli.exporting.export import export
from environment_store.cli.exporting.run import run
from environment_store.cli.exporting.shell import export_shell

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register `export`, `export-shell`, `export-credentials` and `run` on the `envs` app.

    Every command is registered with `cls=EnvsCommand` (`PassthroughCommand` for `run`).

    Args:
        app: The `envs` app.
    """
    app.command("export", cls=EnvsCommand)(export)
    app.command("export-shell", cls=EnvsCommand)(export_shell)
    app.command("export-credentials", cls=EnvsCommand)(export_credentials)
    app.command("run", cls=PassthroughCommand)(run)
