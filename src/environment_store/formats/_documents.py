"""Shared checks for JSON and TOML documents."""

from collections.abc import Mapping

from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_store_name, validate_variables

__all__ = ["NestedInputError", "flat_variables", "nested_variables"]


class NestedInputError(ValidationError):
    """A JSON or TOML import has a nested object, e.g. a nested export (D33).

    Its `hint` names `nested=True`; the CLI names its `--nested` option instead (D47).

    Attributes:
        name: The key that holds the nested object.
    """

    name: str

    def __init__(self, *, format_name: str, name: str) -> None:
        """Create the error for a nested object.

        Args:
            format_name: `JSON` or `TOML`.
            name: The key that holds the nested object.
        """
        self.name = name
        super().__init__(
            f"{format_name} input has a nested object under {name!r}",
            hint=(
                "nested input (e.g. an export with nested=True) is refused, import a flat object "
                "of string values instead"
            ),
        )


def flat_variables(document: object, *, format_name: str) -> dict[str, str]:
    """Check that a parsed document is a flat object of string values (D33).

    Args:
        document: The parsed document (an untyped boundary).
        format_name: `JSON` or `TOML`, used in error messages.

    Returns:
        The variables, validated.

    Raises:
        NestedInputError: The document has a nested object (e.g. a nested export).
        ValidationError: The document is not a mapping, has non-string values, or has invalid
            names or values. Values are never echoed.
    """
    if not isinstance(document, Mapping):
        message = f"{format_name} input must be a flat object of string values"
        raise ValidationError(message)
    variables: dict[str, str] = {}
    for name, value in document.items():
        if isinstance(value, Mapping):
            raise NestedInputError(format_name=format_name, name=str(name))
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
