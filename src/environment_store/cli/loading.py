"""`load_for_reading` and `reading_sources`: the store list, keys and prompts of reading commands.

Order of work: validate the store names and `-k`, check that every store exists (one listing),
refuse stores that share a set key variable, resolve the secrets in load order (each
store at most once, prompts only when interactive), then load. A typo never costs a prompt,
and a wrong key is not asked for again.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import typer

from environment_store.cli.key_options import parse_reading_keys
from environment_store.cli.secrets import resolve_existing
from environment_store.cli.state import get_state
from environment_store.config.secrets import SecretResolver
from environment_store.config.settings import Settings
from environment_store.core.errors import KeyRequiredError, StoreNotFoundError, ValidationError
from environment_store.core.names import key_variable
from environment_store.core.validation import validate_store_name
from environment_store.library.environment import Environment
from environment_store.library.sources import Source
from environment_store.library.store import EnvironmentStore

if TYPE_CHECKING:
    from environment_store.core.secrets import Secret

__all__ = ["load_for_reading", "reading_sources", "store_list"]


def store_list(stores: Sequence[str] | None, settings: Settings) -> tuple[str, ...]:
    """Return the effective store list.

    Positional stores win, then the stores of `ENV_STORE_LOAD`, then the project file's.

    Args:
        stores: The positional stores, or `None` / empty.
        settings: The resolved settings.

    Returns:
        The validated names in load order (repeats kept).

    Raises:
        ValidationError: No stores anywhere, or an invalid name.
    """
    names = tuple(stores) if stores else settings.default_stores
    if not names:
        message = (
            "no stores given: name stores, set ENV_STORE_LOAD, or set 'stores' in .envstore.toml"
        )
        raise ValidationError(message)
    for name in names:
        validate_store_name(name)
    return names


def load_for_reading(
    ctx: typer.Context,
    *,
    stores: Sequence[str] | None,
    keys: Sequence[str] | None,
    first_wins: bool,
) -> Environment:
    """Load the stores of a reading command (`ls`, `get`, `export`, `export-shell`, `run`).

    Args:
        ctx: The command's context.
        stores: The positional stores; `None` or empty for the default list (`store_list`).
        keys: The `-k` values.
        first_wins: Whether `--first-wins` was given.

    Returns:
        The loaded stores, merged by the resolved merge order.

    Raises:
        ValidationError: As for `reading_sources`.
        StoreNotFoundError: As for `reading_sources`.
        CryptoError: As for `reading_sources`, or a wrong key.
    """
    environment, sources = reading_sources(ctx, stores=stores, keys=keys)
    order = get_state(ctx).settings().merge_order(first_wins=first_wins)
    return environment.load(sources, order=order)


def reading_sources(
    ctx: typer.Context, *, stores: Sequence[str] | None, keys: Sequence[str] | None
) -> tuple[EnvironmentStore, list[Source]]:
    """Resolve the stores of a reading command and the key of every encrypted one.

    Args:
        ctx: The command's context.
        stores: The positional stores; `None` or empty for the default list (`store_list`).
        keys: The `-k` values.

    Returns:
        The open store and the sources in load order, each encrypted one with its secret.

    Raises:
        ValidationError: Bad names or `-k` values, keys for plaintext stores, stores that
            share a set `ENV_STORE_KEY_<STORE>` without `-k` for each, or a key in both
            `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD`.
        StoreNotFoundError: Stores that do not exist (all named).
        CryptoError: Missing keys or keys that do not fit the store; with several stores, a
            missing key's hint names the store-bound form `-k <store>=<path>`.
    """
    state = get_state(ctx)
    names = store_list(stores, state.settings())
    sources = parse_reading_keys(keys or (), names)
    environment = state.open_store(ctx)
    missing: list[str] = []
    for name in dict.fromkeys(names):
        try:
            environment.store_info(name)
        except StoreNotFoundError as error:
            # The adapter's own wording, with its location, as in every other command.
            missing.append(str(error))
    if missing:
        raise StoreNotFoundError("; ".join(missing))
    resolver = SecretResolver(environment, state.secret_input("-k -"))
    distinct = tuple(dict.fromkeys(names))
    # Before any key is read or asked for: a shared key variable is ambiguous.
    resolver.check_key_variables(distinct, explicit=sources.keys())
    secrets: dict[str, Secret | None] = {}
    for name in distinct:
        try:
            secrets[name] = resolve_existing(state, resolver, name, sources.get(name))
        except KeyRequiredError as error:
            if len(distinct) == 1:
                raise
            # The resolver's hint names the shorthand, which works with one store only.
            message = (
                f"store {name!r} is encrypted and no key or passphrase was given: pass it "
                f"with -k {name}=<path> (or -k {name}=- for stdin), or set {key_variable(name)}"
            )
            raise KeyRequiredError(message) from error
    return environment, [Source(name, key=secrets[name]) for name in names]
