"""`envs export-shell`: POSIX statements that load stores into the current shell.

Only POSIX shells are supported; other shells use `envs run`.

A child process cannot change its parent's environment, so the statements are printed for
`eval "$(envs export-shell …)"`. Prompts go to stderr, so stdout holds only the
statements.
"""

import typer

from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import (
    FirstWinsOpt,
    NestedPrefixOpt,
    OverwriteOpt,
    ReadKeysOpt,
    StoresArg,
)
from environment_store.cli.output import out
from environment_store.formats.shell import posix_exports

__all__ = ["export_shell"]


def export_shell(  # noqa: PLR0913 - the options of envs export-shell
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    overwrite: OverwriteOpt = False,
    nested: NestedPrefixOpt = False,
    first_wins: FirstWinsOpt = False,
    keys: ReadKeysOpt = None,
) -> None:
    """Print statements that load stores into a POSIX shell.

    Use it as: eval "$(envs export-shell STORES...)". Variables already set in the shell are
    kept unless -o is given.
    """
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    variables = environment.nested_flat() if nested else environment.variables()
    out(posix_exports(variables, overwrite=overwrite), newline=False)
