"""`load_for_reading`: the store list, keys and prompts of reading commands (§6.0, PD 18).

Order of work: validate the store names and `-k`, check that every store exists (one listing),
resolve the secrets in load order (each store at most once, prompts only when interactive),
then load. A typo never costs a prompt, and a wrong key is not asked for again.
"""

from collections.abc import Sequence

import typer

from environment_store.cli.key_options import parse_reading_keys
from environment_store.cli.secrets import resolve_existing
from environment_store.cli.state import get_state
from environment_store.config.secrets import SecretResolver
from environment_store.config.settings import Settings
from environment_store.core.errors import StoreNotFoundError, ValidationError
from environment_store.core.validation import validate_store_name
from environment_store.library.environment import Environment
from environment_store.library.sources import Source

__all__ = ["load_for_reading", "store_list"]


def store_list(stores: Sequence[str] | None, settings: Settings) -> tuple[str, ...]:
    """Return the effective store list: positional stores replace the project file's.

    Args:
        stores: The positional stores, or `None` / empty.
        settings: The resolved settings.

    Returns:
        The validated names in load order (repeats kept).

    Raises:
        ValidationError: No stores anywhere, or an invalid name.
    """
    names = tuple(stores) if stores else settings.stores
    if not names:
        message = "no stores given: name stores, or set 'stores' in .envstore.toml"
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
        stores: The positional stores; `None` or empty for the project file's list.
        keys: The `-k` values.
        first_wins: Whether `--first-wins` was given.

    Returns:
        The loaded stores, merged by the resolved merge order.

    Raises:
        ValidationError: Bad names or `-k` values, keys for plaintext stores.
        StoreNotFoundError: Stores that do not exist (all named).
        CryptoError: Missing or wrong keys.
    """
    state = get_state(ctx)
    settings = state.settings()
    names = store_list(stores, settings)
    sources = parse_reading_keys(keys or (), names)
    environment = state.open_store(ctx)
    existing = {info.name for info in environment.list_stores()}
    missing = [name for name in dict.fromkeys(names) if name not in existing]
    if missing:
        message = f"stores not found: {', '.join(missing)}"
        raise StoreNotFoundError(message)
    resolver = SecretResolver(environment, state.secret_input("-k -"))
    secrets = {
        name: resolve_existing(state, resolver, name, sources.get(name))
        for name in dict.fromkeys(names)
    }
    return environment.load(
        [Source(name, key=secrets[name]) for name in names],
        order=settings.merge_order(first_wins=first_wins),
    )
