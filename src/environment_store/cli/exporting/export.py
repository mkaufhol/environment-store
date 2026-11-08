"""`envs export`: write merged or nested stores as dotenv, JSON or TOML.

The output goes to stdout unless `-f` names a file. Files hold decrypted secrets, so they are
written with mode `0600` and never replaced without `--force`. The format is checked before any
store is loaded, so a missing `-t` never costs a key prompt.
"""

from pathlib import Path
from typing import Final

import typer

from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import (
    FirstWinsOpt,
    ForceOpt,
    NestedOpt,
    OutputFileOpt,
    ReadKeysOpt,
    StoresArg,
    TypeOpt,
    resolve_format,
)
from environment_store.cli.output import err, out

__all__ = ["export"]

_STDOUT: Final = "-"


def export(  # noqa: PLR0913 - the options of envs export
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    file: OutputFileOpt = None,
    fmt: TypeOpt = None,
    force: ForceOpt = False,
    nested: NestedOpt = False,
    first_wins: FirstWinsOpt = False,
    keys: ReadKeysOpt = None,
) -> None:
    """Export stores as dotenv, JSON or TOML.

    Writes to stdout unless -f names a file (mode 0600, replaced only with --force).
    """
    target = None if file is None or file == _STDOUT else Path(file)
    resolved = resolve_format(target, fmt)
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    if target is None:
        # --force has nothing to replace on stdout and is accepted without effect.
        out(environment.dumps(resolved, nested=nested), newline=False)
        return
    environment.to_file(target, fmt=resolved, nested=nested, force=force)
    err(f"exported to '{target}'")
