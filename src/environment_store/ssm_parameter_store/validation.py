from pathlib import Path


def make_string_parameter_store_compatible(string: str) -> str:
    """
    Convert a string to be a valid pathlike string that can be used as a parameter key in AWS Parameter Store.
    Null strings are not allowed.

    :param string: The string to convert
    :return: The parameter store compatible string
    """
    if not string or string.isspace():
        raise ValueError("String cannot be empty.")
    path = Path(string)
    if len(path.parts) == 1:
        return path.parts[0]
    if not path.is_absolute():
        path = Path(f"/{string}")
    return str(path)


def validate_string(string: str, raises: bool = True) -> bool:
    """
    Validate a string to check, if it can be stored as a parameter key in AWS. Allowed characters are a-zA-Z0-9_.-/

    :param string: The string to validate
    :param raises: If set to True, the method will raise a ValueError with the invalid characters marked in the error message.
    :return: True if valid, False if invalid and raises is False
    """
    if not string or string.isspace():
        if raises:
            raise ValueError("String cannot be empty.")
        return False

    valid_pathlike = make_string_parameter_store_compatible(string)
    if valid_pathlike != string:
        if raises:
            raise ValueError(
                f"Invalid pathlike string. Use make_string_pathlike to format the string.\n"
                f"Original: {string}\n"
                f"Valid: {valid_pathlike}"
            )
        return False

    allowed_group_symbols = ["/", "-", "_", "."]
    error_str = ""

    for char in string:
        if char.isalnum() or char in allowed_group_symbols:
            error_str += " "
        else:
            error_str += "^"

    if "^" in error_str and raises:
        raise ValueError(
            f"Illegal characters:\n"
            f"{string}\n"
            f"{error_str}\n"
            f"Allowed characters: {' '.join(allowed_group_symbols)}"
        )

    return "^" not in error_str
