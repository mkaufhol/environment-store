"""Shared option and argument types of the `envs` commands (spec §6, D14, D16, D33).

Use them as annotations of keyword-only parameters (ruff FBT), e.g.::

    def ls(
        ctx: typer.Context,
        stores: StoresArg = None,
        *,
        keys: ReadKeysOpt = None,
        first_wins: FirstWinsOpt = False,
        as_json: JsonOpt = False,
    ) -> None: ...

Defaults belong in the signature: `None` for optional values and lists, `False` for flags.
`StoreOpt` has no default: `-s` is required. Paths that may be `-` (stdin / stdout) are
strings; parse them with `key_options.parse_writing_key` or compare with `"-"`.
"""

from pathlib import Path
from typing import Annotated

import typer

from environment_store.formats.infer import Format

__all__ = [
    "CreateKeyOpt",
    "FileOpt",
    "FirstWinsOpt",
    "ForceOpt",
    "GenerateKeyOpt",
    "JsonOpt",
    "NestedOpt",
    "NewKeyOpt",
    "OverwriteOpt",
    "PassphraseOpt",
    "ReadKeysOpt",
    "StoreOpt",
    "StoresArg",
    "TypeOpt",
    "WriteKeyOpt",
    "YesOpt",
]

StoresArg = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[STORES]...",
        help="Stores in load order; the last one wins (default: 'stores' in .envstore.toml).",
        show_default=False,
    ),
]
StoreOpt = Annotated[
    str, typer.Option("-s", "--store", metavar="STORE", help="The store to change.")
]
ReadKeysOpt = Annotated[
    list[str] | None,
    typer.Option(
        "-k",
        "--key",
        metavar="STORE=PATH",
        help="Key or passphrase file of a store, '-' for stdin; repeatable. With one store, "
        "-k PATH is enough. Default: [keys] in .envstore.toml, else a prompt on a terminal.",
        show_default=False,
    ),
]
WriteKeyOpt = Annotated[
    str | None,
    typer.Option(
        "-k",
        "--key",
        metavar="PATH|-",
        help="Key or passphrase file of the store, '-' for stdin. Default: [keys] in "
        ".envstore.toml, else a prompt on a terminal.",
        show_default=False,
    ),
]
CreateKeyOpt = Annotated[
    str | None,
    typer.Option(
        "-k",
        "--key",
        metavar="PATH|-",
        help="Encrypt with this existing key file ('-' for stdin); needs -e.",
        show_default=False,
    ),
]
NewKeyOpt = Annotated[
    str | None,
    typer.Option(
        "--new-key",
        metavar="PATH|-",
        help="Encrypt with this existing key file ('-' for stdin).",
        show_default=False,
    ),
]
GenerateKeyOpt = Annotated[
    Path | None,
    typer.Option(
        "--generate-key",
        metavar="PATH",
        help="Encrypt with a new key file written to PATH (mode 0600, never overwritten).",
        show_default=False,
    ),
]
PassphraseOpt = Annotated[
    bool,
    typer.Option(
        "--passphrase",
        help="Encrypt with a passphrase: read from stdin when piped, else asked twice.",
    ),
]
FirstWinsOpt = Annotated[
    bool,
    typer.Option(
        "--first-wins",
        help="The first store wins instead of the last (overrides ENV_STORE_ORDERED_OVERWRITE).",
    ),
]
OverwriteOpt = Annotated[
    bool, typer.Option("-o", "--overwrite", help="Overwrite existing variables.")
]
NestedOpt = Annotated[
    bool, typer.Option("--nested", help="Keep stores apart: STORE__NAME or one table per store.")
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print one JSON document.")]
YesOpt = Annotated[bool, typer.Option("-y", "--yes", help="Do not ask for confirmation.")]
FileOpt = Annotated[
    str | None,
    typer.Option(
        "-f", "--file", metavar="PATH|-", help="File to use; '-' or none for stdin / stdout."
    ),
]
TypeOpt = Annotated[
    Format | None,
    typer.Option(
        "-t",
        "--type",
        help="File format; inferred from the file name when omitted.",
        case_sensitive=False,
        show_default=False,
    ),
]
ForceOpt = Annotated[bool, typer.Option("--force", help="Replace an existing output file.")]
