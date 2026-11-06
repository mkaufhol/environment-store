"""TOML import and export (spec §6.10, §6.11).

Exports use `environment_store._toml` (the standard library only reads TOML): flat key/value
lines, or one `[table]` per store when nested. Imports accept only flat string values (D33).
"""

import tomllib
from collections.abc import Mapping

from environment_store._toml import dumps as toml_dumps
from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_variables
from environment_store.formats._documents import flat_variables, nested_variables

__all__ = ["dumps", "dumps_nested", "loads"]


def dumps(variables: Mapping[str, str]) -> str:
    """Serialize variables as flat TOML key/value lines.

    Args:
        variables: Variable names and values, in output order.

    Returns:
        The TOML text; empty for no variables.

    Raises:
        ValidationError: A name or value is invalid.
    """
    return toml_dumps(validate_variables(variables))


def dumps_nested(stores: Mapping[str, Mapping[str, str]]) -> str:
    """Serialize stores as one TOML table each (`--nested`).

    Args:
        stores: Store names and their variables, in load order.

    Returns:
        The TOML text; empty for no stores.

    Raises:
        ValidationError: A store name, variable name or value is invalid.
    """
    return toml_dumps(nested_variables(stores))


def loads(text: str) -> dict[str, str]:
    """Parse flat TOML key/value pairs of strings.

    Args:
        text: The TOML text.

    Returns:
        The variables in document order.

    Raises:
        ValidationError: The text is not valid TOML, has tables or non-string values, or has
            invalid names or values.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        message = f"invalid TOML: {err}"
        raise ValidationError(message) from err
    except RecursionError as err:
        message = "invalid TOML input: it is nested too deeply"
        raise ValidationError(message) from err
    except ValueError as err:
        # For example an integer beyond Python's int-string conversion limit; the builtin's
        # message is not echoed.
        message = "invalid TOML input: it contains a number that is too long"
        raise ValidationError(message) from err
    return flat_variables(document, format_name="TOML")
