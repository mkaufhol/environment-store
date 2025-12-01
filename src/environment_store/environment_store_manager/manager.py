from .schemas import Variable
from .decorators import validate_hierarchy
from .adapter.abstract_adapter import AbstractAdapter


class EnvironmentStoreManager:
    """
    High-level interface for managing environment variables.

    This class provides a consistent API for environment variable operations
    regardless of the underlying storage backend (Parameter Store, Secrets Manager, etc.).

    You can use this class to manage variables in a hierarchical structure:
    organisation > project > environment > service > variable

    Each level can have a set of variables. Variables are unique within a level, but not across levels.

    Usage:
        # Using dependency injection
        adapter = ParameterStoreAdapter(region="us-east-1")
        manager = EnvironmentStoreManager(adapter=adapter)
    """

    def __init__(self, adapter: AbstractAdapter):
        self.adapter = adapter

    @validate_hierarchy
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
        Set a variable value. If the variable does not exist, it will be created.

        :param name: Variable name/key
        :param value: Variable value
        :param organisation: Organisation name (optional)
        :param project: Project name (optional)
        :param environment: Environment name (optional)
        :param service: Service name (optional)
        """
        return self.adapter.set_variable(
            name, value, organisation, project, environment, service
        )

    @validate_hierarchy
    def set_variables(
        self,
        variables: list[Variable] | dict[str, str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        if isinstance(variables, dict):
            variables = [Variable(name=name, value=value) for name, value in variables.items()]
        return self.adapter.set_variables(
            variables, organisation, project, environment, service
        )

    @validate_hierarchy
    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        """
        Get a specific variable value.
        """
        return self.adapter.get_variable(name, organisation, project, environment, service)

    @validate_hierarchy
    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        """
        Get all variables under a specific hierarchy level.
        """
        return self.adapter.get_variables(
            organisation=organisation, project=project, environment=environment, service=service
        )

    def get_organisations(self) -> list[str]:
        """
        Get all organisations.
        """
        return self.adapter.get_organisations()

    def get_projects(self, organisation: str) -> list[str]:
        """
        Get all projects for an organisation.
        """
        return self.adapter.get_projects(organisation)

    @validate_hierarchy
    def get_environments(self, organisation: str, project: str) -> list[str]:
        """
        Get all environments for a project.
        """
        return self.adapter.get_environments(organisation, project)

    @validate_hierarchy
    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        """
        Get all services for an environment.
        """
        return self.adapter.get_services(organisation, project, environment)

    def get_root_variables(self) -> list[Variable]:
        """
        Get all root variables.
        """
        return self.get_variables()

    def get_organisation_variables(
        self, organisation: str, include_parent: bool = True, overwrite_parent: bool = True
    ) -> list[Variable]:
        """
        Get all variables for an organisation.

        :param organisation: The organisation to get variables for
        :param include_parent: Whether to include the variables from the parent level (root level)
        :param overwrite_parent: If there are duplicate variable names, overwrite the parent value (root level) with the organisation value
        :return: A list of variables
        """
        variables = []
        if include_parent:
            variables.append(self.get_variables())
        return self.overwrite_hierarchy_variables(
            variables,
            self.get_variables(organisation=organisation),
            overwrite_parent=overwrite_parent,
        )

    def get_project_variables(
        self,
        organisation: str,
        project: str,
        include_parent: bool = True,
        overwrite_parent: bool = True,
    ) -> list[Variable]:
        """
        Get all variables for a project.

        :param organisation: The organisation to get variables for
        :param project: The project to get variables for
        :param include_parent: Whether to include the variables from the parent level (organisation and root level)
        :param overwrite_parent: If there are duplicate variable names, overwrite the parent value (organisation and root level) with the project value
        :return: A list of variables
        """
        variables = []
        if include_parent:
            variables.append(
                self.get_organisation_variables(organisation, include_parent=include_parent)
            )
        return self.overwrite_hierarchy_variables(
            variables,
            self.get_variables(organisation=organisation, project=project),
            overwrite_parent=overwrite_parent,
        )

    def get_environment_variables(
        self,
        organisation: str,
        project: str,
        environment: str,
        include_parent: bool = True,
        overwrite_parent: bool = True,
    ) -> list[Variable]:
        """
        Get all variables for an environment.

        :param organisation: The organisation to get variables for
        :param project: The project to get variables for
        :param environment: The environment to get variables for
        :param include_parent: Whether to include the variables from the parent level (project, organisation and root level)
        :param overwrite_parent: If there are duplicate variable names, overwrite the parent value (project, organisation and root level) with the environment value
        :return: A list of variables
        """
        variables = []
        if include_parent:
            variables.append(
                self.get_project_variables(organisation, project, include_parent=include_parent)
            )
        return self.overwrite_hierarchy_variables(
            variables,
            self.get_variables(
                organisation=organisation, project=project, environment=environment
            ),
            overwrite_parent=overwrite_parent,
        )

    def get_service_variables(
        self,
        organisation: str,
        project: str,
        environment: str,
        service: str,
        include_parent: bool = True,
        overwrite_parent: bool = True,
    ) -> list[Variable]:
        """
        Get all variables for a service.

        :param organisation: The organisation to get variables for
        :param project: The project to get variables for
        :param environment: The environment to get variables for
        :param service: The service to get variables for
        :param include_parent: Whether to include the variables from the parent level (environment, project, organisation and root level)
        :param overwrite_parent: If there are duplicate variable names, overwrite the parent value (environment, project, organisation and root level) with the service value
        :return: A list of variables
        """
        variables = []
        if include_parent:
            variables.append(
                self.get_environment_variables(
                    organisation, project, environment, include_parent=include_parent
                )
            )
        return self.overwrite_hierarchy_variables(
            variables,
            self.get_variables(
                organisation=organisation,
                project=project,
                environment=environment,
                service=service,
            ),
            overwrite_parent=overwrite_parent,
        )

    @validate_hierarchy
    def get_variables_as_dict(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, str]:
        variables = self.get_variables(
            organisation=organisation, project=project, environment=environment, service=service
        )
        return {variable.name: variable.value for variable in variables}

    @validate_hierarchy
    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ):
        """
        Delete a variable.
        """
        return self.adapter.delete_variable(name, organisation, project, environment, service)

    @validate_hierarchy
    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ):
        """
        Delete multiple variables.
        """
        return self.adapter.delete_variables(names, organisation, project, environment, service)

    @staticmethod
    def overwrite_hierarchy_variables(
        variables: list[Variable],
        overwrite_variables: list[Variable],
        overwrite_parent: bool = True,
    ) -> list[Variable]:
        """
        Overwrite variables in the first list with variables from the second list.
        """
        if overwrite_variables is None:
            raise ValueError("overwrite_variables must be a list")
        if variables is None:
            raise ValueError("variables must be a list")

        overwrite_dict = {variable.name: variable for variable in overwrite_variables}
        variables_dict = {variable.name: variable for variable in variables}
        if overwrite_parent:
            variables_dict.update(overwrite_dict)
            return list(variables_dict.values())
        overwrite_dict.update(variables_dict)
        return sorted(list(overwrite_dict.values()), key=lambda x: x.name)
