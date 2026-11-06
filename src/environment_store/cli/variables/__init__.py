"""The variable commands: ls, get, set, rm, import (C3, spec §6.6-§6.10)."""

import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.variables.importing import import_variables
from environment_store.cli.variables.reading import get_variable, list_variables
from environment_store.cli.variables.writing import remove_variables, set_variables

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the commands of this package on the `envs` app.

    Every command is registered with `cls=EnvsCommand` (`PassthroughCommand` for `run`).

    Args:
        app: The `envs` app.
    """
    app.command("ls", cls=EnvsCommand)(list_variables)
    app.command("get", cls=EnvsCommand)(get_variable)
    app.command("set", cls=EnvsCommand)(set_variables)
    app.command("rm", cls=EnvsCommand)(remove_variables)
    app.command("import", cls=EnvsCommand)(import_variables)
