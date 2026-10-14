class VariableExistsError(Exception):
    """Raised when creating a variable that already exists."""


class VariableNotFoundError(Exception):
    """Raised when updating a variable that does not exist."""
