"""AWS Parameter Store Manager - A Python library to manage AWS Parameter Store."""

from .ssm_parameter_store import ParameterStore

__version__ = "0.1.0"

__all__ = [
    "ParameterStore",
]
