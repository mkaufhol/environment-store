class VariableExistsError(Exception):
    """Raised when creating a variable that already exists."""


class VariableNotFoundError(Exception):
    """Raised when updating a variable that does not exist."""


class ConfirmationMismatchError(ValueError):
    """Raised when a destructive operation is not confirmed with the exact level name."""
