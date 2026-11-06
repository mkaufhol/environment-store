"""Shared checks for JSON and TOML documents."""

from collections.abc import Mapping

from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_store_name, validate_variables

__all__ = ["flat_variables", "nested_variables"]


def flat_variables(document: object, *, format_name: str) -> dict[str, str]:
    """Check that a parsed document is a flat object of string values (D33).

    Args:
        document: The parsed document (an untyped boundary).
        format_name: `JSON` or `TOML`, used in error messages.

    Returns:
        The variables, validated.

    Raises:
        ValidationError: The document is not a mapping, has nested objects (e.g. a `--nested`
            export) or non-string values, or has invalid names or values. Values are never
            echoed.
    """
    if not isinstance(document, Mapping):
        message = f"{format_name} input must be a flat object of string values"
        raise ValidationError(message)
    variables: dict[str, str] = {}
    for name, value in document.items():
        if isinstance(value, Mapping):
            message = (
                f"{format_name} input has a nested object under {name!r}; nested input (e.g. a "
                "--nested export) is refused, import a flat object of string values instead"
            )
            raise ValidationError(message)
        if not isinstance(value, str):
            message = (
                f"{format_name} value of {name!r} must be a string, got {type(value).__name__}"
            )
            raise ValidationError(message)
        variables[str(name)] = value
    return validate_variables(variables)


def nested_variables(stores: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    """Validate a nested document: store name → variables (`--nested`, §6.11).

    Args:
        stores: Store names and their variables, in load order.

    Returns:
        A validated copy.

    Raises:
        ValidationError: A store name, variable name or value is invalid.
    """
    return {
        validate_store_name(store): validate_variables(variables)
        for store, variables in stores.items()
    }
