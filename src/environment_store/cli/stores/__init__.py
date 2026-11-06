"""The store commands: ls-store, create-store, rm-store, cp-store, mv-store (C2)."""

import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.stores.copying import cp_store, mv_store
from environment_store.cli.stores.lifecycle import create_store, rm_store
from environment_store.cli.stores.listing import ls_store

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the commands of this package on the `envs` app.

    Every command is registered with `cls=EnvsCommand`, so the configuration is validated
    before each runs (PD 10).

    Args:
        app: The `envs` app.
    """
    app.command("ls-store", cls=EnvsCommand)(ls_store)
    app.command("create-store", cls=EnvsCommand)(create_store)
    app.command("rm-store", cls=EnvsCommand)(rm_store)
    app.command("cp-store", cls=EnvsCommand)(cp_store)
    app.command("mv-store", cls=EnvsCommand)(mv_store)
