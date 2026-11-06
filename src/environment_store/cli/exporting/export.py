"""`envs export`: write merged or nested stores as dotenv, JSON or TOML (spec §6.11, D22, D30).

The output goes to stdout unless `-f` names a file. Files are written with mode `0600` and never
replaced without `--force` (PD 4). The format is checked before any store is loaded, so a
missing `-t` never costs a key prompt.
"""

from pathlib import Path
from typing import Final

import typer

from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import (
    FileOpt,
    FirstWinsOpt,
    ForceOpt,
    NestedOpt,
    ReadKeysOpt,
    StoresArg,
    TypeOpt,
)
from environment_store.cli.output import err, out
from environment_store.core.errors import ValidationError
from environment_store.formats.infer import Format, infer_format

__all__ = ["export"]

_STDOUT: Final = "-"


def export(  # noqa: PLR0913 - the options of spec §6.11
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    file: FileOpt = None,
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
    resolved = _format(target, fmt)
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    if target is None:
        # --force has nothing to replace on stdout and is accepted without effect.
        out(environment.dumps(resolved, nested=nested), newline=False)
        return
    environment.to_file(target, fmt=resolved, nested=nested, force=force)
    err(f"exported to '{target}'")


def _format(target: Path | None, fmt: Format | None) -> Format:
    # D22: -t wins; otherwise the file name decides, and stdout is dotenv.
    if fmt is not None:
        return fmt
    if target is None:
        return Format.DOTENV
    inferred = infer_format(target)
    if inferred is None:
        message = (
            f"cannot infer the format of '{target}' from its name: pass -t dotenv, -t json "
            "or -t toml"
        )
        raise ValidationError(message)
    return inferred
