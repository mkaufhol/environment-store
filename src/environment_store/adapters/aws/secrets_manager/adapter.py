"""
AbstractAdapter implementation backed by AWS Secrets Manager.

Every hierarchy level is stored as ONE secret containing a JSON object of its variables:

    <prefix>/<organisation>/<project>/<environment>/<service>   ->   {"NAME": "value", ...}

The root level is the secret named ``<prefix>`` itself. This keeps the number of (billed)
secrets small, but writes are read-modify-write: two concurrent writers on the same level
can overwrite each other's changes (last write wins).
"""

import json

from environment_store.core.abstract_adapter import AbstractAdapter
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

from ..hierarchy import child_names, level_segments, validate_segment
from .secrets_manager import SecretsManager


class SecretsManagerAdapter(AbstractAdapter):
    """
    Store environment variables in AWS Secrets Manager.

    :param region: The AWS region to use. Ignored if ``secrets_manager`` is given.
    :param prefix: Path prefix below which all secrets are stored (e.g. ``"myapp/config"``).
        It is also the name of the root level secret.
    :param secrets_manager: An existing ``SecretsManager`` to use instead of creating one.
    """

    def __init__(
        self,
        region: str | None = None,
        prefix: str = "environment-store",
        secrets_manager: SecretsManager | None = None,
    ):
        if secrets_manager is None:
            if region is None:
                raise ValueError("Either region or secrets_manager must be provided")
            secrets_manager = SecretsManager(region=region, clean_string=False)
        self.secrets_manager = secrets_manager
        self.prefix = [validate_segment(s, "prefix") for s in prefix.strip("/").split("/") if s]
        if not self.prefix:
            raise ValueError("prefix must not be empty")

    def _secret_name(self, segments: list[str]) -> str:
        return "/".join(self.prefix + segments)

    def _read(self, segments: list[str]) -> dict[str, str]:
        raw = self.secrets_manager.get_secret_string(self._secret_name(segments))
        if raw is None:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError(
                f"Secret {self._secret_name(segments)!r} is not a JSON object of variables"
            )
        return data

    def _write(self, segments: list[str], data: dict[str, str]) -> None:
        name = self._secret_name(segments)
        if data:
            self.secrets_manager.put_secret_string(name, json.dumps(data))
        else:
            self.secrets_manager.delete_secret(name)

    def _levels(self) -> list[list[str]]:
        """Hierarchy path of every secret below the prefix (excluding the root secret)."""
        root = self._secret_name([])
        names = self.secrets_manager.list_secret_names(root + "/")
        depth = len(self.prefix)
        return [n.split("/")[depth:] for n in names]

    def set_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        self.set_variables(
            [Variable(name=name, value=value)], organisation, project, environment, service
        )

    def set_variables(
        self,
        variables: list[Variable],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        """Write all variables of the level in a single secret update (atomic per level)."""
        segments = level_segments(organisation, project, environment, service)
        if not variables:
            return
        for variable in variables:
            validate_segment(variable.name, "variable name")
        data = self._read(segments)
        data.update({v.name: v.value for v in variables})
        self._write(segments, data)

    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        segments = level_segments(organisation, project, environment, service)
        validate_segment(name, "variable name")
        return self._read(segments).get(name)

    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        segments = level_segments(organisation, project, environment, service)
        return [Variable(name=k, value=v) for k, v in self._read(segments).items()]

    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        validate_segment(name, "variable name")
        result = self.delete_variables([name], organisation, project, environment, service)
        return bool(result["deleted"])

    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, list[str]]:
        """Delete variables; the level's secret is removed once its last variable is gone."""
        if not names:
            raise ValueError("names must not be empty")
        segments = level_segments(organisation, project, environment, service)
        for name in names:
            validate_segment(name, "variable name")
        data = self._read(segments)
        deleted = [n for n in names if n in data]
        not_found = [n for n in names if n not in data]
        if deleted:
            for name in deleted:
                del data[name]
            self._write(segments, data)
        return {"deleted": deleted, "not_found": not_found}

    def get_organisations(self) -> list[str]:
        return child_names([], self._levels())

    def get_projects(self, organisation: str) -> list[str]:
        return child_names(level_segments(organisation), self._levels())

    def get_environments(self, organisation: str, project: str) -> list[str]:
        return child_names(level_segments(organisation, project), self._levels())

    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        return child_names(level_segments(organisation, project, environment), self._levels())

    def create_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        if self.variable_exists(name, organisation, project, environment, service):
            raise VariableExistsError(f"Variable '{name}' already exists.")
        self.set_variable(name, value, organisation, project, environment, service)

    def update_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        if not self.variable_exists(name, organisation, project, environment, service):
            raise VariableNotFoundError(f"Variable '{name}' not found.")
        self.set_variable(name, value, organisation, project, environment, service)
