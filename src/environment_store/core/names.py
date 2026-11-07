"""Names derived from store names (D30, D40, D53).

A store name in SCREAMING_SNAKE_CASE is upper case with `-` turned into `_`. It is the prefix of
nested variables (`CUSTOMER_A__DB_HOST`, D30) and the suffix of the variable that may hold an
existing store's key (`ENV_STORE_KEY_CUSTOMER_A`, D53). Store names start with a letter (D40),
so both are always valid POSIX variable names. These functions expect a validated store name.
"""

from typing import Final

__all__ = ["KEY_VARIABLE_PREFIX", "is_key_variable", "key_variable", "screaming_snake"]

KEY_VARIABLE_PREFIX: Final = "ENV_STORE_KEY_"
"""Every key variable starts with it; `run` removes all such variables from the child (D53)."""


def screaming_snake(store: str) -> str:
    """Return a store name in SCREAMING_SNAKE_CASE: `customer-a` → `CUSTOMER_A`.

    Args:
        store: A valid store name.

    Returns:
        The name in upper case with `-` replaced by `_`.
    """
    return store.upper().replace("-", "_")


def key_variable(store: str) -> str:
    """Return the environment variable that may hold a store's key (D53).

    Args:
        store: A valid store name.

    Returns:
        E.g. `ENV_STORE_KEY_CUSTOMER_A` for `customer-a`.
    """
    return KEY_VARIABLE_PREFIX + screaming_snake(store)


def is_key_variable(name: str) -> bool:
    """Tell whether an environment variable name is a key variable (D53).

    Args:
        name: The variable name.

    Returns:
        Whether it starts with `ENV_STORE_KEY_` (case-sensitive).
    """
    return name.startswith(KEY_VARIABLE_PREFIX)
