"""The key commands: keygen, rekey, encrypt (C4)."""

import typer

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Register the commands of this package on the `envs` app (filled in by C4).

    Every command is registered with `cls=EnvsCommand` (`PassthroughCommand` for `run`).

    Args:
        app: The `envs` app.
    """
