"""JSON import and export (spec §6.10, §6.11).

Exports are indented objects of strings, flat or nested per store. Imports accept only flat
objects of string values (D33).
"""

import json
from collections.abc import Mapping

from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_variables
from environment_store.formats._documents import flat_variables, nested_variables

__all__ = ["dumps", "dumps_nested", "loads"]


def dumps(variables: Mapping[str, str]) -> str:
    """Serialize variables as a flat JSON object.

    Args:
        variables: Variable names and values, in output order.

    Returns:
        The JSON text with a final newline.

    Raises:
        ValidationError: A name or value is invalid.
    """
    return _dump(validate_variables(variables))


def dumps_nested(stores: Mapping[str, Mapping[str, str]]) -> str:
    """Serialize stores as a JSON object of objects (`--nested`).

    Args:
        stores: Store names and their variables, in load order.

    Returns:
        The JSON text with a final newline.

    Raises:
        ValidationError: A store name, variable name or value is invalid.
    """
    return _dump(nested_variables(stores))


def loads(text: str) -> dict[str, str]:
    """Parse a flat JSON object of string values.

    Args:
        text: The JSON text.

    Returns:
        The variables in document order.

    Raises:
        ValidationError: The text is not valid JSON, has duplicate keys, is not a flat object of
            strings, or has invalid names or values.
    """
    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicates)
    except json.JSONDecodeError as err:
        message = f"invalid JSON at line {err.lineno}, column {err.colno}: {err.msg}"
        raise ValidationError(message) from err
    except RecursionError as err:
        message = "invalid JSON input: it is nested too deeply"
        raise ValidationError(message) from err
    except ValidationError:
        raise
    except ValueError as err:
        # For example an integer beyond Python's int-string conversion limit; the builtin's
        # message is not echoed.
        message = "invalid JSON input: it contains a number that is too long"
        raise ValidationError(message) from err
    return flat_variables(document, format_name="JSON")


def _dump(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = f"JSON key {key!r} appears more than once"
            raise ValidationError(message)
        result[key] = value
    return result
