"""`envs ls` and `envs get`: read the merged variables of stores (spec §6.6, §6.7, D16, D33).

Both load through `load_for_reading` (store list, `-k`, project keys, prompts, merge order).
Names are output sorted (PD 13); `--json` documents follow PD 23.
"""

from typing import Annotated

import typer

from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import FirstWinsOpt, JsonOpt, ReadKeysOpt, StoresArg
from environment_store.cli.output import (
    JsonValue,
    display_value,
    emit_json,
    out,
    table,
    write_value,
)
from environment_store.cli.state import get_state
from environment_store.core.errors import NotFoundError
from environment_store.core.validation import validate_variable_name

__all__ = ["get_variable", "list_variables"]

ValuesOpt = Annotated[bool, typer.Option("-v", "--values", help="Also show the values.")]
SourceOpt = Annotated[
    bool,
    typer.Option(
        "--source",
        help="Show the store each winning value comes from; also works without -v (prints "
        "NAME and store).",
    ),
]
KeyArg = Annotated[str, typer.Argument(metavar="KEY", help="The variable name.")]


def list_variables(  # noqa: PLR0913 - one parameter per option of the command
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    values: ValuesOpt = False,
    source: SourceOpt = False,
    first_wins: FirstWinsOpt = False,
    keys: ReadKeysOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """List the variables of one or more stores, merged in load order."""
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    merged = environment.with_sources()
    if as_json:
        documents: list[JsonValue] = []
        for name, (value, store) in merged.items():
            document: dict[str, JsonValue] = {"name": name}
            if values:
                document["value"] = value
            if source:
                document["store"] = store
            documents.append(document)
        emit_json(documents)
        return
    entries = [
        f"{name}={display_value(value)}" if values else name for name, (value, _) in merged.items()
    ]
    if source:
        # The store column comes last, so the table's trimming never touches a value.
        rows = [(entry, store) for entry, (_, store) in zip(entries, merged.values(), strict=True)]
        entries = table(rows).split("\n") if rows else []
    for entry in entries:
        out(entry)


def get_variable(  # noqa: PLR0913 - one parameter per argument and option
    ctx: typer.Context,
    key: KeyArg,
    stores: StoresArg = None,
    *,
    first_wins: FirstWinsOpt = False,
    keys: ReadKeysOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Print the value of a variable; with several stores, the value that wins.

    The raw value is printed without a trailing newline unless stdout is a terminal, so
    $(envs get NAME store) works for multi-line values too.
    """
    # A typo in the name never costs a prompt.
    validate_variable_name(key)
    environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
    merged = environment.with_sources()
    if key not in merged:
        searched = tuple(dict.fromkeys(name for name, _ in environment.stores))
        # One wording whatever the number of stores: only the noun follows the count.
        noun = "store" if len(searched) == 1 else "stores"
        message = f"variable {key!r} not found in {noun} {', '.join(map(repr, searched))}"
        raise NotFoundError(message)
    value, store = merged[key]
    if as_json:
        emit_json({"name": key, "value": value, "store": store})
        return
    write_value(value, tty=get_state(ctx).runtime.stdout_is_tty())
