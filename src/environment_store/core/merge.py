"""Merging of stores in load order, nested mode and bool settings.

Merging is a pure core function so that every frontend (library, CLI, TUI) behaves identically,
including the output order: the stores' variables in load order, each store's sorted by name
in code point order, a variable shared by several stores at its first position.
Error messages name stores and variables but never echo a value.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Final

from environment_store.core.errors import ConfigurationError, ValidationError
from environment_store.core.names import screaming_snake
from environment_store.core.validation import validate_store_name, validate_variable_name

__all__ = [
    "MergeOrder",
    "merge",
    "merge_with_sources",
    "nested",
    "nested_flat",
    "nested_flat_key",
    "order_from_setting",
    "parse_bool_setting",
]

_NESTED_SEPARATOR: Final[str] = "__"
_TRUE_VALUES: Final[frozenset[str]] = frozenset({"true", "1", "yes"})
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"false", "0", "no"})


class MergeOrder(StrEnum):
    """Which store wins when a variable is present in several stores."""

    LAST_WINS = "last_wins"
    """The store loaded last wins (`ordered_overwrite = true`, the default)."""
    FIRST_WINS = "first_wins"
    """A variable already set is not overwritten by later stores (`ordered_overwrite = false`)."""


def merge_with_sources(
    stores: Sequence[tuple[str, Mapping[str, str]]],
    *,
    order: MergeOrder = MergeOrder.LAST_WINS,
) -> dict[str, tuple[str, str]]:
    """Merge stores in load order and remember which store each value comes from.

    Args:
        stores: `(store name, variables)` pairs in load order.
        order: Which store wins for a variable present in several stores.

    Returns:
        Variable name → `(value, winning store name)` in output order: stores in load
        order, each store's variables sorted by name (code point order), a variable present in
        several stores at the position of its first appearance with the value `order` chooses.
    """
    result: dict[str, tuple[str, str]] = {}
    for store, variables in stores:
        # Within one store by name; a dict keeps a key's first position on reassignment.
        for name, value in sorted(variables.items()):
            if order is MergeOrder.LAST_WINS or name not in result:
                result[name] = (value, store)
    return result


def merge(
    stores: Sequence[tuple[str, Mapping[str, str]]],
    *,
    order: MergeOrder = MergeOrder.LAST_WINS,
) -> dict[str, str]:
    """Merge stores in load order into one set of variables.

    Args:
        stores: `(store name, variables)` pairs in load order.
        order: Which store wins for a variable present in several stores.

    Returns:
        Variable name → winning value in output order (see `merge_with_sources`).
    """
    return {name: value for name, (value, _) in merge_with_sources(stores, order=order).items()}


def nested(stores: Sequence[tuple[str, Mapping[str, str]]]) -> dict[str, dict[str, str]]:
    """Keep each store in its own namespace instead of merging (`--nested`).

    Args:
        stores: `(store name, variables)` pairs in load order.

    Returns:
        Store name → copy of its variables, in load order.

    Raises:
        ValidationError: A store is listed more than once, so one namespace would be lost.
    """
    result: dict[str, dict[str, str]] = {}
    for store, variables in stores:
        if store in result:
            message = f"store {store!r} is listed more than once; nested mode needs each store once"
            raise ValidationError(message)
        result[store] = dict(variables)
    return result


def nested_flat_key(store: str, variable: str) -> str:
    """Build the flat key of a variable in nested mode.

    The store name in SCREAMING_SNAKE_CASE (`-` becomes `_`), a double underscore, then the
    variable name unchanged: `customer-a`, `DB_HOST` → `CUSTOMER_A__DB_HOST`.

    Args:
        store: The store name.
        variable: The variable name.

    Returns:
        The flat key.

    Raises:
        ValidationError: The store or variable name is invalid.
    """
    validate_store_name(store)
    validate_variable_name(variable)
    return f"{screaming_snake(store)}{_NESTED_SEPARATOR}{variable}"


def nested_flat(stores: Sequence[tuple[str, Mapping[str, str]]]) -> dict[str, str]:
    """Flatten nested mode into prefixed variables for dotenv and shell output.

    Args:
        stores: `(store name, variables)` pairs in load order.

    Returns:
        Flat key → value, in load order.

    Raises:
        ValidationError: A store is listed more than once, or two variables map to the same flat
            key (e.g. stores `customer-a` and `customer_a`); the message names both origins.
    """
    result: dict[str, str] = {}
    origins: dict[str, tuple[str, str]] = {}
    for store, variables in nested(stores).items():
        for variable, value in variables.items():
            key = nested_flat_key(store, variable)
            if key in origins:
                first_store, first_variable = origins[key]
                message = (
                    f"nested key {key} is produced by both {first_variable} in store "
                    f"{first_store!r} and {variable} in store {store!r}; "
                    "rename one of them or export without nested mode"
                )
                raise ValidationError(message)
            origins[key] = (store, variable)
            result[key] = value
    return result


def parse_bool_setting(raw: str, *, setting: str) -> bool:
    """Parse a boolean setting such as `ENV_STORE_ORDERED_OVERWRITE`.

    Args:
        raw: The raw text; `true/false/1/0/yes/no`, case-insensitive.
        setting: Name of the setting, used in the error message.

    Returns:
        The parsed value.

    Raises:
        ConfigurationError: The text is not one of the accepted values.
    """
    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    message = f"invalid value {raw!r} for {setting}: use true/false/1/0/yes/no"
    raise ConfigurationError(message)


def order_from_setting(*, ordered_overwrite: bool) -> MergeOrder:
    """Map the `ordered_overwrite` setting to a merge order.

    Args:
        ordered_overwrite: `True` means last wins, `False` means first wins.

    Returns:
        The merge order.
    """
    return MergeOrder.LAST_WINS if ordered_overwrite else MergeOrder.FIRST_WINS
