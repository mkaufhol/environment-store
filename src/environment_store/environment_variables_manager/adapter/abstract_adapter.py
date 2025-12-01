"""
Abstract base class for environment variable storage adapters.

This module defines the interface that all storage adapters must implement
to work with the EnvironmentVariablesManager.
"""

from abc import ABC, abstractmethod
from typing import Optional


class EnvironmentVariablesManagerAdapter(ABC):
    """
    Abstract base class for storage adapters.

    Adapters translate between the high-level EnvironmentVariablesManager interface
    and specific AWS services (Parameter Store, Secrets Manager, etc.).
    """

    @abstractmethod
    def set_project(self, project: str) -> None:
        """
        Set the project name for the adapter.

        :param project: Project name
        """
        pass

    @abstractmethod
    def set_environment(self, environment: str) -> None:
        """
        Set the environment name for the adapter.

        :param environment: Environment name
        """
        pass

    def set_service(self, service: str) -> None:
        """
        Set the service name for the adapter.

        :param service: Service name
        """
        pass

    @abstractmethod
    def create_variable(
        self,
        name: str,
        value: str,
    ) -> None:
        """
        Create a new environment variable.

        :param name: Variable name/key
        :param value: Variable value
        :param overwrite: If True, overwrite existing variable; if False, raise error if exists
        :raises: VariableAlreadyExistsError if variable exists and overwrite=False
        """
        pass

    @abstractmethod
    def update_variable(
        self,
        name: str,
        value: str,
    ) -> None:
        """
        Update an existing environment variable.

        :param name: Variable name/key
        :param value: New variable value
        :raises: VariableNotFoundError if variable doesn't exist
        """
        pass

    def get_variable(self, name: str) -> Optional[str]:
        """
        Get a single environment variable value.

        :param name: Variable name/key
        :return: Variable value if exists, None otherwise
        """
        pass

    def get_variables(self, project: str, environment: str, service: str) -> dict[str, str]:
        """
        Get multiple environment variables under a path.

        :param project: Project name
        :param environment: Environment name
        :param service: Service name
        :return: Dictionary of variable names to values
        """
        pass

    def delete_variable(self, name: str) -> None:
        """
        Delete a single environment variable.

        :param name: Variable name/key
        """
        pass

    def delete_variables(self, names: list[str]) -> dict[str, list[str]]:
        """
        Delete multiple environment variables.

        :param names: List of variable names/keys
        :return: Dictionary with 'deleted' and 'failed' keys
        """
        pass
