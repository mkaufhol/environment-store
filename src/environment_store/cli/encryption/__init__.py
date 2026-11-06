"""The key commands: keygen, rekey, encrypt (C4, spec §4.5)."""

import typer

from environment_store.cli._typer import EnvsCommand, OfflineCommand
from environment_store.cli.encryption.encrypt import encrypt, rekey
from environment_store.cli.encryption.keygen import keygen

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register `keygen`, `rekey` and `encrypt` on the `envs` app.

    Every command is registered with `cls=EnvsCommand`; `keygen` with `OfflineCommand`, which
    reads neither the connection nor the project file (D44).

    Args:
        app: The `envs` app.
    """
    app.command("keygen", cls=OfflineCommand)(keygen)
    app.command("rekey", cls=EnvsCommand)(rekey)
    app.command("encrypt", cls=EnvsCommand)(encrypt)
