"""
AbstractAdapter implementation backed by the AWS Systems Manager Parameter Store.

Every variable is stored as one parameter. The hierarchy is mapped to the parameter path:

    /<prefix>/<organisation>/<project>/<environment>/<service>/<NAME>

Variables at a higher level simply have a shorter path, root variables live at ``/<NAME>``.
"""

from typing import Literal

from environment_store.core.abstract_adapter import AbstractAdapter
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

from ..hierarchy import child_names, level_segments, validate_segment
from .exceptions import ParameterAlreadyExists, ParameterNotFoundError
from .parameter_store import ParameterStore

# SSM accepts at most 10 names per delete_parameters call
_DELETE_BATCH_SIZE = 10


class ParameterStoreAdapter(AbstractAdapter):
    """
    Store environment variables in the AWS Parameter Store.

    :param region: The AWS region to use. Ignored if ``parameter_store`` is given.
    :param prefix: Optional path prefix (e.g. ``"myapp"`` or ``"myapp/config"``) below which all
        variables are stored.
    :param parameter_type: The SSM parameter type used for written variables. Defaults to
        ``SecureString`` so values are encrypted with the default KMS key.
    :param parameter_store: An existing ``ParameterStore`` to use instead of creating one.
    """

    def __init__(
        self,
        region: str | None = None,
        prefix: str = "",
        parameter_type: Literal["String", "SecureString"] = "SecureString",
        parameter_store: ParameterStore | None = None,
    ):
        if parameter_store is None:
            if region is None:
                raise ValueError("Either region or parameter_store must be provided")
            parameter_store = ParameterStore(region=region, clean_string=False)
        self.parameter_store = parameter_store
        self.parameter_type = parameter_type
        self.prefix = [validate_segment(s, "prefix") for s in prefix.strip("/").split("/") if s]

    def _path(self, segments: list[str]) -> str:
        return "/" + "/".join(self.prefix + segments)

    def _name(self, name: str, segments: list[str]) -> str:
        return f"{self._path(segments).rstrip('/')}/{validate_segment(name, 'variable name')}"

    def _containers(self) -> list[list[str]]:
        """Hierarchy path (without variable name) of every stored parameter below the prefix."""
        parameters = self.parameter_store.get_parameters_by_path(
            self._path([]), recursive=True
        ).Parameters
        depth = len(self.prefix)
        return [p.Name.strip("/").split("/")[depth:-1] for p in parameters]

    def set_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        segments = level_segments(organisation, project, environment, service)
        self.parameter_store.update_or_create_parameter(
            self._name(name, segments), value, parameter_type=self.parameter_type
        )

    def set_variables(
        self,
        variables: list[Variable],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """Set all variables, failing fast: variables before the first error stay written."""
        segments = level_segments(organisation, project, environment, service)
        # Validate everything up front so invalid input writes nothing
        names = [self._name(v.name, segments) for v in variables]
        for name, variable in zip(names, variables):
            self.parameter_store.update_or_create_parameter(
                name, variable.value, parameter_type=self.parameter_type
            )

    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        segments = level_segments(organisation, project, environment, service)
        return self.parameter_store.get_parameter_value(self._name(name, segments))

    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        segments = level_segments(organisation, project, environment, service)
        parameters = self.parameter_store.get_parameters_by_path(
            self._path(segments), recursive=False
        ).Parameters
        return [Variable(name=p.Name.rsplit("/", 1)[-1], value=p.Value) for p in parameters]

    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        segments = level_segments(organisation, project, environment, service)
        try:
            self.parameter_store.delete_parameter(self._name(name, segments))
        except ParameterNotFoundError:
            return False
        return True

    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, list[str]]:
        if not names:
            raise ValueError("names must not be empty")
        segments = level_segments(organisation, project, environment, service)
        full_names = {self._name(name, segments): name for name in names}
        deleted: list[str] = []
        not_found: list[str] = []
        keys = list(full_names)
        for i in range(0, len(keys), _DELETE_BATCH_SIZE):
            response = self.parameter_store.delete_parameters(keys[i : i + _DELETE_BATCH_SIZE])
            deleted += [full_names[n] for n in response.DeletedParameters]
            not_found += [full_names[n] for n in response.InvalidParameters]
        return {"deleted": deleted, "not_found": not_found}

    def get_organisations(self) -> list[str]:
        return child_names([], self._containers())

    def get_projects(self, organisation: str) -> list[str]:
        prefix = level_segments(organisation)
        return child_names(prefix, self._containers())

    def get_environments(self, organisation: str, project: str) -> list[str]:
        prefix = level_segments(organisation, project)
        return child_names(prefix, self._containers())

    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        prefix = level_segments(organisation, project, environment)
        return child_names(prefix, self._containers())

    def create_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        segments = level_segments(organisation, project, environment, service)
        try:
            self.parameter_store.create_parameter(
                self._name(name, segments), value, parameter_type=self.parameter_type
            )
        except ParameterAlreadyExists as e:
            raise VariableExistsError(str(e)) from e

    def update_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        segments = level_segments(organisation, project, environment, service)
        try:
            self.parameter_store.update_parameter(
                self._name(name, segments), value, parameter_type=self.parameter_type
            )
        except ParameterNotFoundError as e:
            raise VariableNotFoundError(str(e)) from e
