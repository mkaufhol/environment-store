"""The key commands: keygen, rekey, encrypt (C4, spec §4.5)."""

import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.encryption.encrypt import encrypt, rekey
from environment_store.cli.encryption.keygen import keygen

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register `keygen`, `rekey` and `encrypt` on the `envs` app.

    Every command is registered with `cls=EnvsCommand`.

    Args:
        app: The `envs` app.
    """
    app.command("keygen", cls=EnvsCommand)(keygen)
    app.command("rekey", cls=EnvsCommand)(rekey)
    app.command("encrypt", cls=EnvsCommand)(encrypt)
