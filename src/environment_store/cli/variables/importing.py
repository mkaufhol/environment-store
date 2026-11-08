"""`envs import`: fill an existing store from a dotenv, JSON or TOML file.

The input is read and parsed before the store's key is resolved, so a missing file or a
malformed document never costs a prompt. JSON and TOML input must be flat; dotenv input
is never interpolated. An empty document changes nothing and needs no key, but
a given or project key is still validated.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

import typer

from environment_store.cli.options import (
    InputFileOpt,
    OverwriteOpt,
    StoreOpt,
    TypeOpt,
    WriteKeyOpt,
    resolve_format,
)
from environment_store.cli.output import err
from environment_store.cli.secrets import existing_secret
from environment_store.cli.state import get_state
from environment_store.config.key_variables import has_environment_key
from environment_store.formats import dotenv, json_format, toml_format
from environment_store.formats.infer import Format
from environment_store.library.files import read_input_file

__all__ = ["import_variables"]

_STDIN: Final = "-"
_INPUT_PURPOSE: Final = "the import input"
_LOADERS: Final[Mapping[Format, Callable[[str], dict[str, str]]]] = MappingProxyType(
    {Format.DOTENV: dotenv.loads, Format.JSON: json_format.loads, Format.TOML: toml_format.loads}
)


def import_variables(  # noqa: PLR0913 - one parameter per option of the command
    ctx: typer.Context,
    *,
    store: StoreOpt,
    file: InputFileOpt = None,
    fmt: TypeOpt = None,
    overwrite: OverwriteOpt = False,
    key: WriteKeyOpt = None,
) -> None:
    """Fill an existing store from a dotenv, JSON or TOML file, or stdin (dotenv by default).

    JSON and TOML input must be a flat object of string values; dotenv input is imported
    literally, ${X} is never expanded. Existing variables are an error unless -o is given.
    """
    path = None if file is None or file == _STDIN else Path(file)
    resolved = resolve_format(path, fmt)
    state = get_state(ctx)
    environment = state.open_store(ctx)
    # Exit 2 for a missing store before any input is read.
    environment.store_info(store)
    if path is None:
        state.claim_stdin(_INPUT_PURPOSE)
        if key == _STDIN:
            # Refused here (stdin is read once), also when the document turns out empty.
            state.claim_stdin("-k -")
        text = state.read_stdin()
    else:
        text = read_input_file(path)
    variables = _LOADERS[resolved](text)
    if not variables:
        # Nothing is written, but a given, environment or project key is still
        # checked: only the prompt for a missing key is skipped.
        given = key is not None or has_environment_key(store, state.runtime.environ())
        if given or store in state.settings().key_paths:
            existing_secret(ctx, store, key)
        err(f"nothing to import into store '{store}'")
        return
    secret = existing_secret(ctx, store, key)
    environment.set_many(store, variables, key=secret, overwrite=overwrite)
    count = len(variables)
    err(f"imported {count} variable{'' if count == 1 else 's'} into store '{store}'")
