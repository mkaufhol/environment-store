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

Store parameters complete existing store names and path parameters let the shell complete
files (D54). Defaults belong in the signature: `None` for optional values and lists, `False`
for flags.
`StoreOpt` has no default: `-s` is required. Paths that may be `-` (stdin / stdout) are
strings; parse them with `key_options.parse_writing_key` or compare with `"-"`.
"""

from pathlib import Path
from typing import Annotated

import typer

from environment_store.cli.completion.candidates import PathType, ReadKeyType, complete_stores
from environment_store.core.errors import ValidationError
from environment_store.formats.infer import Format, infer_format

__all__ = [
    "CreateKeyOpt",
    "FirstWinsOpt",
    "ForceOpt",
    "GenerateKeyOpt",
    "InputFileOpt",
    "JsonOpt",
    "NestedOpt",
    "NestedPrefixOpt",
    "NewKeyOpt",
    "OutputFileOpt",
    "OverwriteOpt",
    "PassphraseOpt",
    "ReadKeysOpt",
    "StoreOpt",
    "StoresArg",
    "TypeOpt",
    "WriteKeyOpt",
    "YesOpt",
    "resolve_format",
]

StoresArg = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[STORES]...",
        help="Stores in load order; the last one wins (default: 'stores' in .envstore.toml).",
        show_default=False,
        autocompletion=complete_stores,
    ),
]
StoreOpt = Annotated[
    str,
    typer.Option(
        "-s",
        "--store",
        metavar="STORE",
        help="The store to change.",
        autocompletion=complete_stores,
    ),
]
ReadKeysOpt = Annotated[
    list[str] | None,
    typer.Option(
        "-k",
        "--key",
        metavar="STORE=PATH",
        help="Key or passphrase file of a store, '-' for stdin; repeatable. With one store, "
        "-k PATH is enough. Default: ENV_STORE_KEY_<STORE>, else [keys] in .envstore.toml, "
        "else a prompt on a terminal.",
        show_default=False,
        click_type=ReadKeyType(),
    ),
]
WriteKeyOpt = Annotated[
    str | None,
    typer.Option(
        "-k",
        "--key",
        metavar="PATH|-",
        help="Key or passphrase file of the store, '-' for stdin. Default: ENV_STORE_KEY_<STORE>, "
        "else [keys] in .envstore.toml, else a prompt on a terminal.",
        show_default=False,
        click_type=PathType(),
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
        click_type=PathType(),
    ),
]
NewKeyOpt = Annotated[
    str | None,
    typer.Option(
        "--new-key",
        metavar="PATH|-",
        help="Encrypt with this existing key file ('-' for stdin).",
        show_default=False,
        click_type=PathType(),
    ),
]
GenerateKeyOpt = Annotated[
    Path | None,
    typer.Option(
        "--generate-key",
        metavar="PATH",
        help="Encrypt with a new key file written to PATH (mode 0600, never overwritten).",
        show_default=False,
        click_type=PathType(),
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
    bool,
    typer.Option(
        "--nested",
        help="Keep stores apart: one table per store (json, toml) or STORE__NAME (dotenv).",
    ),
]
"""`--nested` of `export`, which has both forms."""
NestedPrefixOpt = Annotated[
    bool,
    typer.Option("--nested", help="Prefix each variable with its store name: STORE__NAME."),
]
"""`--nested` of `export-shell` and `run`, which only prefix (spec §6.12, §6.13)."""
JsonOpt = Annotated[bool, typer.Option("--json", help="Print one JSON document.")]
YesOpt = Annotated[bool, typer.Option("-y", "--yes", help="Do not ask for confirmation.")]
InputFileOpt = Annotated[
    str | None,
    typer.Option(
        "-f",
        "--file",
        metavar="PATH|-",
        help="Input file; '-' or none reads stdin.",
        click_type=PathType(),
    ),
]
OutputFileOpt = Annotated[
    str | None,
    typer.Option(
        "-f",
        "--file",
        metavar="PATH|-",
        help="Output file; '-' or none writes to stdout.",
        click_type=PathType(),
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


def resolve_format(path: Path | None, fmt: Format | None) -> Format:
    """Resolve the format of `import` and `export` (D22).

    Args:
        path: The file; `None` for stdin / stdout.
        fmt: The `-t` value, if given.

    Returns:
        `-t` if given; else the format inferred from the file name; dotenv for stdin / stdout.

    Raises:
        ValidationError: The file name determines no format.
    """
    if fmt is not None:
        return fmt
    if path is None:
        return Format.DOTENV
    inferred = infer_format(path)
    if inferred is None:
        message = (
            f"cannot infer the format of '{path}' from its name: pass -t dotenv, -t json or -t toml"
        )
        raise ValidationError(message)
    return inferred
