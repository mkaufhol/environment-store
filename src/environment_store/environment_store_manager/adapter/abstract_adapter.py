"""
Abstract base class for environment variable storage adapters.

This module defines the interface that all storage adapters must implement
to work with the EnvironmentStoreManager. The adapter pattern allows the
manager to work with different storage backends (AWS Parameter Store,
AWS Secrets Manager, local file storage, etc.) through a consistent interface.

Hierarchy Structure:
    The environment store uses a hierarchical structure for organizing variables:

    root (global)
    └── organisation
        └── project
            └── environment
                └── service
                    └── variable

    Variables can be stored at any level of this hierarchy. When retrieving
    variables, the manager can optionally include variables from parent levels,
    with child values overriding parent values for duplicate names.

Implementation Requirements:
    - All concrete adapters must inherit from AbstractAdapter
    - All abstract methods must be implemented
    - Implementations should handle their own connection management
    - Implementations should be thread-safe if used in multi-threaded contexts
    - Implementations should handle cleanup in __del__ or provide explicit close methods
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..schemas import Variable


class AbstractAdapter(ABC):
    """
    Abstract base class for environment variable storage adapters.

    This class defines the interface that all storage adapters must implement
    to work with the EnvironmentStoreManager. Adapters translate between the
    high-level manager interface and specific storage backends.

    The adapter is responsible for:
        - Storing and retrieving environment variables
        - Managing the hierarchical namespace (organisation/project/environment/service)
        - Translating between the Variable schema and the backend's native format
        - Handling backend-specific errors and translating them to appropriate exceptions

    Hierarchy Rules:
        The hierarchy must be respected when specifying locations:
        - service requires environment, project, and organisation
        - environment requires project and organisation
        - project requires organisation
        - organisation can be specified alone
        - All None values indicate the root level

    Example:
        >>> class MyStorageAdapter(AbstractAdapter):
        ...     def __init__(self, connection_string: str):
        ...         self.connection = connect(connection_string)
        ...
        ...     def set_variable(self, name, value, organisation=None, ...):
        ...         path = self._build_path(organisation, project, environment, service)
        ...         self.connection.store(path, name, value)
        ...
        >>> adapter = MyStorageAdapter(
        ...     "my://connection"
        ... )
        >>> manager = (
        ...     EnvironmentStoreManager(
        ...         adapter=adapter
        ...     )
        ... )
    """

    @abstractmethod
    def set_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """
        Set a variable value, creating it if it doesn't exist or updating if it does.

        This is the primary method for storing variables. It should handle both
        creation of new variables and updates to existing ones (upsert behavior).

        Args:
            name: The variable name/key. Must be a non-empty string.
                  Implementations may impose additional constraints on valid names
                  (e.g., no special characters, maximum length).
            value: The variable value to store. Must be a string.
                   Implementations may impose size limits on values.
            organisation: The organisation name for scoping the variable.
                         If None, the variable is stored at the root level.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project (e.g., 'dev', 'prod').
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            None

        Raises:
            ValueError: If name is empty or contains invalid characters for the backend.
            ValueError: If hierarchy rules are violated (e.g., service without environment).
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to write to the specified location.

        Example:
            >>> # Set a root-level variable
            >>> adapter.set_variable(
            ...     "GLOBAL_TIMEOUT", "30"
            ... )
            >>>
            >>> # Set an organisation-level variable
            >>> adapter.set_variable(
            ...     "ORG_API_KEY",
            ...     "key123",
            ...     organisation="acme",
            ... )
            >>>
            >>> # Set a service-level variable
            >>> adapter.set_variable(
            ...     "DB_HOST",
            ...     "localhost",
            ...     organisation="acme",
            ...     project="webapp",
            ...     environment="dev",
            ...     service="api",
            ... )

        Implementation Notes:
            - Should be idempotent: calling with the same arguments multiple times
              should have the same effect as calling once.
            - Should handle concurrent writes gracefully (last-write-wins is acceptable).
            - May need to create intermediate hierarchy levels if they don't exist.
        """
        pass

    @abstractmethod
    def set_variables(
        self,
        variables: list[Variable],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """
        Set multiple variables at once, creating or updating as needed.

        Batch operation for storing multiple variables at the same hierarchy level.
        This method should handle both creation of new variables and updates to
        existing ones (upsert behavior) for each variable in the list.

        Args:
            variables: A list of Variable objects to store. Each Variable must have
                      'name' and 'value' string attributes. The list may be empty,
                      in which case this method should be a no-op.
            organisation: The organisation name for scoping the variables.
                         If None, variables are stored at the root level.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project (e.g., 'dev', 'prod').
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            None

        Raises:
            ValueError: If any variable name is empty or contains invalid characters.
            ValueError: If hierarchy rules are violated (e.g., service without environment).
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to write to the specified location.

        Example:
            >>> from environment_store.environment_store_manager.schemas import (
            ...     Variable,
            ... )
            >>>
            >>> # Set multiple root-level variables
            >>> adapter.set_variables(
            ...     [
            ...         Variable(
            ...             name="GLOBAL_TIMEOUT",
            ...             value="30",
            ...         ),
            ...         Variable(
            ...             name="LOG_LEVEL",
            ...             value="INFO",
            ...         ),
            ...     ]
            ... )
            >>>
            >>> # Set multiple service-level variables
            >>> adapter.set_variables(
            ...     [
            ...         Variable(
            ...             name="DB_HOST",
            ...             value="localhost",
            ...         ),
            ...         Variable(
            ...             name="DB_PORT",
            ...             value="5432",
            ...         ),
            ...         Variable(
            ...             name="DB_NAME",
            ...             value="myapp",
            ...         ),
            ...     ],
            ...     organisation="acme",
            ...     project="webapp",
            ...     environment="dev",
            ...     service="api",
            ... )

        Implementation Notes:
            - Should be idempotent: calling with the same arguments multiple times
              should have the same effect as calling once.
            - For backends that support batch operations, this should be more
              efficient than calling set_variable() multiple times.
            - If the backend doesn't support batch writes, implementations may
              iterate and call set_variable() for each variable.
            - Should handle concurrent writes gracefully (last-write-wins is acceptable).
            - If any variable fails to be set, the behavior depends on the backend:
              implementations may either fail fast (stop on first error) or attempt
              to set all variables and report failures. Document the chosen behavior
              in your concrete implementation.
            - An empty variables list should be handled gracefully (no-op).
        """
        pass

    @abstractmethod
    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        """
        Get a single variable value from the specified hierarchy level.

        Retrieves the value of a specific variable at the exact hierarchy level
        specified. This method does NOT search parent levels - it only looks
        at the exact level specified by the parameters.

        Args:
            name: The variable name/key to retrieve. Must be a non-empty string.
            organisation: The organisation name to search in.
                         If None (along with other params), searches root level.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project.
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            str | None: The variable value if found, None if the variable does not
                       exist at the specified hierarchy level.

        Raises:
            ValueError: If name is empty.
            ValueError: If hierarchy rules are violated.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to read from the location.

        Example:
            >>> # Get a root-level variable
            >>> value = adapter.get_variable(
            ...     "GLOBAL_TIMEOUT"
            ... )
            >>> print(value)  # "30" or None
            >>>
            >>> # Get a service-level variable
            >>> db_host = (
            ...     adapter.get_variable(
            ...         "DB_HOST",
            ...         organisation="acme",
            ...         project="webapp",
            ...         environment="dev",
            ...         service="api",
            ...     )
            ... )

        Implementation Notes:
            - Should return None for non-existent variables, not raise an exception.
            - Should only search the exact level specified, not parent levels.
            - The manager handles inheritance/override logic using get_variables().
        """
        pass

    @abstractmethod
    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        """
        Get all variables at a specific hierarchy level.

        Retrieves all variables stored at the exact hierarchy level specified.
        This method does NOT include variables from parent or child levels -
        it only returns variables at the exact level specified.

        Args:
            organisation: The organisation name to search in.
                         If None (along with other params), returns root-level variables.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project.
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            list[Variable]: A list of Variable objects at the specified level.
                           Returns an empty list if no variables exist at that level.
                           Each Variable has 'name' and 'value' string attributes.

        Raises:
            ValueError: If hierarchy rules are violated.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to read from the location.

        Example:
            >>> # Get all root-level variables
            >>> root_vars = (
            ...     adapter.get_variables()
            ... )
            >>> for var in root_vars:
            ...     print(
            ...         f"{var.name}={var.value}"
            ...     )
            >>>
            >>> # Get all variables for a specific environment
            >>> env_vars = (
            ...     adapter.get_variables(
            ...         organisation="acme",
            ...         project="webapp",
            ...         environment="prod",
            ...     )
            ... )

        Implementation Notes:
            - Should return an empty list for levels with no variables, not None.
            - The returned list should contain Variable objects from schemas.py.
            - Order of variables in the returned list is not guaranteed.
            - Should not include variables from child levels (e.g., service variables
              when querying at environment level).
        """
        pass

    @abstractmethod
    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        """
        Delete a single variable from the specified hierarchy level.

        Removes a variable from the exact hierarchy level specified. This operation
        is idempotent - deleting a non-existent variable should not raise an error.

        Args:
            name: The variable name/key to delete. Must be a non-empty string.
            organisation: The organisation name where the variable is stored.
                         If None (along with other params), deletes from root level.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project.
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            bool: True if the variable was deleted, False if it didn't exist.

        Raises:
            ValueError: If name is empty.
            ValueError: If hierarchy rules are violated.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to delete from the location.

        Example:
            >>> # Delete a root-level variable
            >>> deleted = (
            ...     adapter.delete_variable(
            ...         "OLD_CONFIG"
            ...     )
            ... )
            >>> print(
            ...     f"Variable {'was' if deleted else 'was not'} deleted"
            ... )
            >>>
            >>> # Delete a service-level variable
            >>> adapter.delete_variable(
            ...     "DEPRECATED_SETTING",
            ...     organisation="acme",
            ...     project="webapp",
            ...     environment="dev",
            ...     service="api",
            ... )

        Implementation Notes:
            - Should be idempotent: deleting a non-existent variable returns False.
            - Should only delete from the exact level specified.
            - Should not affect variables with the same name at other hierarchy levels.
        """
        pass

    @abstractmethod
    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, list[str]]:
        """
        Delete multiple variables from the specified hierarchy level.

        Batch deletion of variables for efficiency. This method attempts to delete
        all specified variables and reports which deletions succeeded and failed.

        Args:
            names: List of variable names/keys to delete. Must be non-empty.
                  Each name must be a non-empty string.
            organisation: The organisation name where the variables are stored.
                         If None (along with other params), deletes from root level.
            project: The project name within the organisation.
                    Requires organisation to be specified.
            environment: The environment name within the project.
                        Requires both organisation and project to be specified.
            service: The service name within the environment.
                    Requires organisation, project, and environment to be specified.

        Returns:
            dict[str, list[str]]: A dictionary with two keys:
                - 'deleted': List of variable names that were successfully deleted.
                - 'not_found': List of variable names that did not exist.

                Example return value:
                {
                    'deleted': ['VAR1', 'VAR2'],
                    'not_found': ['VAR3']
                }

        Raises:
            ValueError: If names list is empty.
            ValueError: If any name in the list is empty.
            ValueError: If hierarchy rules are violated.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to delete from the location.

        Example:
            >>> # Delete multiple root-level variables
            >>> result = (
            ...     adapter.delete_variables(
            ...         [
            ...             "OLD_VAR1",
            ...             "OLD_VAR2",
            ...             "MISSING",
            ...         ]
            ...     )
            ... )
            >>> print(
            ...     f"Deleted: {result['deleted']}"
            ... )
            >>> print(
            ...     f"Not found: {result['not_found']}"
            ... )
            >>>
            >>> # Delete multiple service-level variables
            >>> result = (
            ...     adapter.delete_variables(
            ...         [
            ...             "TEMP_CONFIG",
            ...             "DEBUG_FLAG",
            ...         ],
            ...         organisation="acme",
            ...         project="webapp",
            ...         environment="dev",
            ...         service="api",
            ...     )
            ... )

        Implementation Notes:
            - Should attempt to delete all variables, even if some fail.
            - Should be atomic where possible (all-or-nothing), but partial
              success is acceptable if the backend doesn't support transactions.
            - Variables that don't exist should be reported in 'not_found', not cause errors.
            - For backends that support batch operations, this should be more
              efficient than calling delete_variable() multiple times.
        """
        pass

    @abstractmethod
    def get_organisations(self) -> list[str]:
        """
        Get all organisation names that have variables or child entities.

        Returns a list of all organisations that exist in the storage backend.
        An organisation "exists" if it has any variables at the organisation level
        or has any projects, environments, or services beneath it.

        Returns:
            list[str]: A list of organisation names. Returns an empty list if
                      no organisations exist. Names are returned as strings.

        Raises:
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to list organisations.

        Example:
            >>> orgs = adapter.get_organisations()
            >>> print(
            ...     orgs
            ... )  # ['acme', 'globex', 'initech']
            >>>
            >>> for org in orgs:
            ...     projects = (
            ...         adapter.get_projects(
            ...             org
            ...         )
            ...     )
            ...     print(
            ...         f"{org}: {len(projects)} projects"
            ...     )

        Implementation Notes:
            - Should return unique organisation names (no duplicates).
            - Order of organisations in the returned list is not guaranteed.
            - Should include organisations that have no direct variables but have
              child projects/environments/services with variables.
            - Empty organisations (no variables and no children) may or may not
              be included depending on the backend's capabilities.
        """
        pass

    @abstractmethod
    def get_projects(self, organisation: str) -> list[str]:
        """
        Get all project names within an organisation.

        Returns a list of all projects that exist under the specified organisation.
        A project "exists" if it has any variables at the project level or has
        any environments or services beneath it.

        Args:
            organisation: The organisation name to list projects for.
                         Must be a non-empty string.

        Returns:
            list[str]: A list of project names within the organisation.
                      Returns an empty list if the organisation has no projects
                      or if the organisation doesn't exist.

        Raises:
            ValueError: If organisation is empty.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to list projects.

        Example:
            >>> projects = (
            ...     adapter.get_projects(
            ...         "acme"
            ...     )
            ... )
            >>> print(
            ...     projects
            ... )  # ['webapp', 'mobile-app', 'data-pipeline']
            >>>
            >>> for project in projects:
            ...     envs = adapter.get_environments(
            ...         "acme", project
            ...     )
            ...     print(
            ...         f"{project}: {envs}"
            ...     )

        Implementation Notes:
            - Should return unique project names (no duplicates).
            - Order of projects in the returned list is not guaranteed.
            - Should return an empty list (not raise an error) if the organisation
              doesn't exist or has no projects.
            - Should include projects that have no direct variables but have
              child environments/services with variables.
        """
        pass

    @abstractmethod
    def get_environments(self, organisation: str, project: str) -> list[str]:
        """
        Get all environment names within a project.

        Returns a list of all environments that exist under the specified
        organisation and project. An environment "exists" if it has any variables
        at the environment level or has any services beneath it.

        Args:
            organisation: The organisation name. Must be a non-empty string.
            project: The project name within the organisation.
                    Must be a non-empty string.

        Returns:
            list[str]: A list of environment names within the project.
                      Returns an empty list if the project has no environments
                      or if the organisation/project doesn't exist.
                      Common values include: 'dev', 'staging', 'prod', 'test'.

        Raises:
            ValueError: If organisation or project is empty.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to list environments.

        Example:
            >>> envs = (
            ...     adapter.get_environments(
            ...         "acme", "webapp"
            ...     )
            ... )
            >>> print(
            ...     envs
            ... )  # ['dev', 'staging', 'prod']
            >>>
            >>> for env in envs:
            ...     services = (
            ...         adapter.get_services(
            ...             "acme",
            ...             "webapp",
            ...             env,
            ...         )
            ...     )
            ...     print(
            ...         f"{env}: {services}"
            ...     )

        Implementation Notes:
            - Should return unique environment names (no duplicates).
            - Order of environments in the returned list is not guaranteed.
            - Should return an empty list (not raise an error) if the organisation
              or project doesn't exist.
            - Should include environments that have no direct variables but have
              child services with variables.
        """
        pass

    @abstractmethod
    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        """
        Get all service names within an environment.

        Returns a list of all services that exist under the specified organisation,
        project, and environment. A service "exists" if it has any variables
        stored at the service level.

        Args:
            organisation: The organisation name. Must be a non-empty string.
            project: The project name within the organisation.
                    Must be a non-empty string.
            environment: The environment name within the project.
                        Must be a non-empty string.

        Returns:
            list[str]: A list of service names within the environment.
                      Returns an empty list if the environment has no services
                      or if the organisation/project/environment doesn't exist.
                      Common values include: 'api', 'web', 'worker', 'scheduler'.

        Raises:
            ValueError: If organisation, project, or environment is empty.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks permission to list services.

        Example:
            >>> services = (
            ...     adapter.get_services(
            ...         "acme",
            ...         "webapp",
            ...         "prod",
            ...     )
            ... )
            >>> print(
            ...     services
            ... )  # ['api', 'web', 'worker']
            >>>
            >>> for service in services:
            ...     vars = adapter.get_variables(
            ...         organisation="acme",
            ...         project="webapp",
            ...         environment="prod",
            ...         service=service,
            ...     )
            ...     print(
            ...         f"{service}: {len(vars)} variables"
            ...     )

        Implementation Notes:
            - Should return unique service names (no duplicates).
            - Order of services in the returned list is not guaranteed.
            - Should return an empty list (not raise an error) if the organisation,
              project, or environment doesn't exist.
            - Services are the leaf level of the hierarchy - they cannot have
              child entities, only variables.
        """
        pass

    # Optional methods that concrete implementations may override

    def create_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """
        Create a new environment variable (fails if it already exists).

        This is an optional method that provides create-only semantics.
        The default implementation delegates to set_variable(), but concrete
        implementations may override this to provide strict create behavior
        that fails if the variable already exists.

        Args:
            name: The variable name/key. Must be a non-empty string.
            value: The variable value to store.
            organisation: The organisation name for scoping the variable.
            project: The project name within the organisation.
            environment: The environment name within the project.
            service: The service name within the environment.

        Returns:
            None

        Raises:
            ValueError: If name is empty or invalid.
            ValueError: If hierarchy rules are violated.
            VariableExistsError: If the variable already exists (implementation-specific).
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks write permission.

        Implementation Notes:
            - Default implementation calls set_variable() (upsert behavior).
            - Override this method if your backend supports create-only operations
              and you want to enforce that variables are not accidentally overwritten.
        """
        return self.set_variable(name, value, organisation, project, environment, service)

    def update_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """
        Update an existing environment variable (fails if it doesn't exist).

        This is an optional method that provides update-only semantics.
        The default implementation delegates to set_variable(), but concrete
        implementations may override this to provide strict update behavior
        that fails if the variable doesn't exist.

        Args:
            name: The variable name/key. Must be a non-empty string.
            value: The new variable value.
            organisation: The organisation name for scoping the variable.
            project: The project name within the organisation.
            environment: The environment name within the project.
            service: The service name within the environment.

        Returns:
            None

        Raises:
            ValueError: If name is empty or invalid.
            ValueError: If hierarchy rules are violated.
            VariableNotFoundError: If the variable doesn't exist (implementation-specific).
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks write permission.

        Implementation Notes:
            - Default implementation calls set_variable() (upsert behavior).
            - Override this method if your backend supports update-only operations
              and you want to ensure variables exist before updating them.
        """
        return self.set_variable(name, value, organisation, project, environment, service)

    def variable_exists(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        """
        Check if a variable exists at the specified hierarchy level.

        This is a convenience method that checks for variable existence.
        The default implementation uses get_variable(), but concrete
        implementations may override this for better performance if the
        backend supports existence checks without retrieving the value.

        Args:
            name: The variable name/key to check.
            organisation: The organisation name to search in.
            project: The project name within the organisation.
            environment: The environment name within the project.
            service: The service name within the environment.

        Returns:
            bool: True if the variable exists, False otherwise.

        Raises:
            ValueError: If name is empty.
            ValueError: If hierarchy rules are violated.
            ConnectionError: If the storage backend is unavailable.
            PermissionError: If the caller lacks read permission.

        Example:
            >>> if adapter.variable_exists(
            ...     "API_KEY",
            ...     organisation="acme",
            ... ):
            ...     print(
            ...         "API key is configured"
            ...     )
            ... else:
            ...     print(
            ...         "API key needs to be set"
            ...     )

        Implementation Notes:
            - Default implementation calls get_variable() and checks for None.
            - Override this method if your backend can check existence more
              efficiently than retrieving the full value.
        """
        return self.get_variable(name, organisation, project, environment, service) is not None
