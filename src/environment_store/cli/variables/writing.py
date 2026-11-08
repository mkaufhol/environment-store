"""`envs set` and `envs rm`: change the variables of one store in one write (spec §6.8, §6.9).

Writing commands name their store with `-s` and never take it from the project file (D33).
Both validate their arguments before reading a key, so a typo never costs a prompt.
"""

from collections.abc import Sequence
from typing import Annotated, Final

import typer

from environment_store.cli.completion.candidates import complete_variables
from environment_store.cli.options import OverwriteOpt, StoreOpt, WriteKeyOpt
from environment_store.cli.output import err
from environment_store.cli.secrets import existing_secret
from environment_store.cli.state import get_state
from environment_store.core.errors import (
    PlaintextNotAllowedError,
    ValidationError,
    VariableExistsError,
)
from environment_store.core.validation import validate_variable_name

__all__ = ["remove_variables", "set_variables", "strip_one_newline"]

_CRLF: Final = "\r\n"
_LF: Final = "\n"

AssignmentsArg = Annotated[
    list[str],
    typer.Argument(
        metavar="KEY=VALUE... | KEY",
        help="KEY=VALUE pairs (plaintext stores only), or one KEY whose value is read from "
        "stdin when piped, else asked twice (hidden).",
        show_default=False,
        autocompletion=complete_variables,
    ),
]
NamesArg = Annotated[
    list[str],
    typer.Argument(
        metavar="KEYS...",
        help="The variables to delete.",
        show_default=False,
        autocompletion=complete_variables,
    ),
]


def set_variables(
    ctx: typer.Context,
    arguments: AssignmentsArg,
    *,
    store: StoreOpt,
    overwrite: OverwriteOpt = False,
    key: WriteKeyOpt = None,
) -> None:
    """Set one or more variables in one store, in a single write.

    KEY=VALUE pairs are refused for encrypted stores, because command lines end up in the
    shell history: give one KEY and pipe its value (one trailing newline is stripped) or type
    it at the hidden prompt.
    """
    parsed = _parse_assignments(arguments)
    state = get_state(ctx)
    environment = state.open_store(ctx)
    encrypted = environment.store_info(store).encrypted
    if isinstance(parsed, dict):
        if encrypted:
            message = (
                f"store {store!r} is encrypted: values on the command line end up in the shell "
                f"history; give one name and pipe its value on stdin "
                f"(envs set -s {store} NAME < FILE) or type it at the hidden prompt "
                f"(envs set -s {store} NAME)"
            )
            raise PlaintextNotAllowedError(message)
        values = parsed
        secret = existing_secret(ctx, store, key)
    else:
        # D35: without a prompt (piped stdin or --noinput) the value comes from stdin.
        from_stdin = not state.interactive()
        if from_stdin:
            # Claimed before the key, so `-k -` is refused before anything is read.
            state.claim_stdin(f"the value of {parsed}")
        secret = existing_secret(ctx, store, key)
        if not overwrite and parsed in environment.variables(store, key=secret):
            # Checked before asking for the value; the write checks again.
            raise VariableExistsError([parsed], store=store)
        if from_stdin:
            value = strip_one_newline(_read_value(state.read_stdin(), store=store, name=parsed))
        else:
            value = state.prompter().new_secret(f"Value of {parsed}: ")
        values = {parsed: value}
    environment.set_many(store, values, key=secret, overwrite=overwrite)
    err(f"set {', '.join(values)} in store '{store}'")


def remove_variables(
    ctx: typer.Context,
    names: NamesArg,
    *,
    store: StoreOpt,
    key: WriteKeyOpt = None,
) -> None:
    """Delete one or more variables from one store, in a single write."""
    for name in names:
        validate_variable_name(name)
    secret = existing_secret(ctx, store, key)
    get_state(ctx).open_store(ctx).delete(store, names, key=secret)
    err(f"removed {', '.join(dict.fromkeys(names))} from store '{store}'")


def strip_one_newline(text: str) -> str:
    """Remove exactly one trailing line ending, CRLF or LF, from a piped value (D38, PD 25).

    Args:
        text: The text read from stdin.

    Returns:
        The text without its last line ending; other carriage returns and
        newlines are kept.
    """
    for ending in (_CRLF, _LF):
        if text.endswith(ending):
            return text.removesuffix(ending)
    return text


def _read_value(text: str, *, store: str, name: str) -> str:
    # D41: zero bytes (< /dev/null, a forgotten pipe in CI) must never blank a variable.
    if not text:
        message = (
            f"no value was read from stdin (it was empty); to set an empty value, send a "
            f"newline (echo | envs set -s {store} {name}) or, for a plain store, use "
            f"envs set -s {store} {name}="
        )
        raise ValidationError(message)
    return text


def _parse_assignments(arguments: Sequence[str]) -> dict[str, str] | str:
    """Split `set`'s arguments into KEY=VALUE pairs or the one bare KEY (D18).

    Returns:
        The pairs, or the bare name.

    Raises:
        ValidationError: Mixed forms, several bare names, a name given twice, or an invalid
            name.
    """
    pairs: dict[str, str] = {}
    bare: list[str] = []
    for argument in arguments:
        name, separator, value = argument.partition("=")
        if not separator:
            bare.append(validate_variable_name(argument))
            continue
        validate_variable_name(name)
        if name in pairs:
            message = f"variable {name!r} is given more than once"
            raise ValidationError(message)
        pairs[name] = value
    if not bare:
        return pairs
    if pairs or len(bare) > 1:
        message = (
            "give either KEY=VALUE pairs, or exactly one KEY whose value is read from stdin or "
            "the prompt"
        )
        raise ValidationError(message)
    return bare[0]
