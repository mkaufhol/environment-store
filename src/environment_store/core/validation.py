"""Validation of store names, variable names and values.

Errors name the offending store or variable but never echo a value, because values may be secrets.
"""

import re
from collections.abc import Mapping
from typing import Final

from environment_store.core.errors import ValidationError

__all__ = [
    "STORE_NAME_PATTERN",
    "VARIABLE_NAME_PATTERN",
    "validate_store_name",
    "validate_value",
    "validate_variable_name",
    "validate_variables",
]

# Lowercase only: store names become file names on case-insensitive file systems (D27).
STORE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Portable POSIX environment variable names, case-sensitive (D33).
VARIABLE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LONE_SURROGATE: Final[re.Pattern[str]] = re.compile("[\ud800-\udfff]")


def validate_store_name(name: str) -> str:
    """Check a store name against D27.

    Args:
        name: The store name.

    Returns:
        The unchanged name.

    Raises:
        ValidationError: The name is not a string or does not match `STORE_NAME_PATTERN`.
    """
    if not isinstance(name, str):
        message = f"store name must be a string, got {type(name).__name__}"
        raise ValidationError(message)
    # fullmatch: `$` alone would also accept a trailing newline.
    if not STORE_NAME_PATTERN.fullmatch(name):
        message = (
            f"invalid store name {name!r}: use 1 to 63 lowercase letters, digits, '_' or '-', "
            f"starting with a letter or digit ({STORE_NAME_PATTERN.pattern})"
        )
        raise ValidationError(message)
    return name


def validate_variable_name(name: str) -> str:
    """Check a variable name against the portable POSIX rule (D33).

    Args:
        name: The variable name.

    Returns:
        The unchanged name.

    Raises:
        ValidationError: The name is not a string or does not match `VARIABLE_NAME_PATTERN`.
    """
    if not isinstance(name, str):
        message = f"variable name must be a string, got {type(name).__name__}"
        raise ValidationError(message)
    if not VARIABLE_NAME_PATTERN.fullmatch(name):
        message = (
            f"invalid variable name {name!r}: use letters, digits and '_', not starting with a "
            f"digit ({VARIABLE_NAME_PATTERN.pattern})"
        )
        raise ValidationError(message)
    return name


def validate_value(value: str, *, variable: str) -> str:
    """Check a variable value against D28: any UTF-8 string without NUL.

    Args:
        value: The value. It is never included in an error message.
        variable: Name of the variable the value belongs to, used in error messages.

    Returns:
        The unchanged value.

    Raises:
        ValidationError: The value is not a string, contains NUL or is not valid UTF-8.
    """
    if not isinstance(value, str):
        message = f"value of variable {variable!r} must be a string, got {type(value).__name__}"
        raise ValidationError(message)
    if "\x00" in value:
        message = (
            f"value of variable {variable!r} contains a NUL character, "
            "which environment variables cannot hold"
        )
        raise ValidationError(message)
    if _LONE_SURROGATE.search(value):
        message = f"value of variable {variable!r} is not valid UTF-8 (it has a lone surrogate)"
        raise ValidationError(message)
    return value


def validate_variables(variables: Mapping[str, str]) -> dict[str, str]:
    """Check every name and value of a variable mapping.

    Args:
        variables: Variable names and values.

    Returns:
        A new `dict` with the same items.

    Raises:
        ValidationError: A name or value is invalid; the message names the first offending
            variable.
    """
    return {
        validate_variable_name(name): validate_value(value, variable=name)
        for name, value in variables.items()
    }
