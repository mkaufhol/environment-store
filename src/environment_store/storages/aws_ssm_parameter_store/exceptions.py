class ParameterAlreadyExists(Exception):
    """Raised when a parameter already exists in the AWS Parameter Store for that group."""

    def __init__(self, parameter_name):
        message = (
            f"Parameter '{parameter_name}' already exists. "
            "Use update_parameter to update or delete_parameter to delete."
        )

        super().__init__(message)


class ParameterNotFoundError(Exception):
    """Raised when a parameter is not found in AWS Parameter Store."""

    def __init__(self, parameter_name):
        message = f"Parameter '{parameter_name}' not found."

        super().__init__(message)
