"""
This module provides a high level interface to manage environment variables on AWS.

The EnvironmentVariablesManager provides a unified interface for managing environment
variables across different AWS storage backends (Parameter Store, Secrets Manager).
"""

from typing import Optional

from .adapter.abstract_adapter import EnvironmentVariablesManagerAdapter


class EnvironmentVariablesManager:
    """
    High-level interface for managing environment variables on AWS.

    This class provides a consistent API for environment variable operations
    regardless of the underlying storage backend (Parameter Store, Secrets Manager).

    Usage:
        # Using dependency injection
        adapter = ParameterStoreAdapter(region="us-east-1")
        manager = EnvironmentVariablesManager(adapter=adapter)

        # Using factory methods
        manager = EnvironmentVariablesManager.from_parameter_store(region="us-east-1")
        manager = EnvironmentVariablesManager.from_secrets_manager(region="us-east-1")
    """

    def __init__(self, adapter: EnvironmentVariablesManagerAdapter):
        """
        Initialize the manager with a storage adapter.

        :param adapter: An instance of a storage adapter (not a class!)
        """
        self.adapter = adapter

    def create_variable(
        self,
        name: str,
        value: str,
        overwrite: bool = False,
        description: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Create a new environment variable.

        :param name: Variable name/key
        :param value: Variable value
        :param overwrite: If True, overwrite existing variable
        :param description: Optional description
        :param tags: Optional tags as key-value pairs
        """
        return self.adapter.create_variable(name, value, overwrite, description, tags)

    def get_variable(self, name: str) -> Optional[str]:
        """
        Get a single environment variable value.

        :param name: Variable name/key
        :return: Variable value if exists, None otherwise
        """
        return self.adapter.get_variable(name)

    def get_variables(self, path: str, recursive: bool = False) -> dict[str, str]:
        """
        Get multiple environment variables under a path.

        :param path: Path prefix to search under
        :param recursive: If True, search recursively
        :return: Dictionary of variable names to values
        """
        return self.adapter.get_variables(path, recursive)

    def update_variable(self, name: str, value: str, description: Optional[str] = None) -> None:
        """
        Update an existing environment variable.

        :param name: Variable name/key
        :param value: New variable value
        :param description: Optional new description
        """
        return self.adapter.update_variable(name, value, description)

    def delete_variable(self, name: str) -> None:
        """
        Delete a single environment variable.

        :param name: Variable name/key
        """
        return self.adapter.delete_variable(name)

    def delete_variables(self, names: list[str]) -> dict[str, list[str]]:
        """
        Delete multiple environment variables.

        :param names: List of variable names/keys
        :return: Dictionary with 'deleted' and 'failed' keys
        """
        return self.adapter.delete_variables(names)

    def variable_exists(self, name: str) -> bool:
        """
        Check if an environment variable exists.

        :param name: Variable name/key
        :return: True if exists, False otherwise
        """
        return self.adapter.variable_exists(name)
