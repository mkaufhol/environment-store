"""
AbstractAdapter implementation backed by AWS Secrets Manager.

The whole store lives in ONE secret named ``<prefix>``, holding a flat JSON object whose keys
are the variable paths below the prefix:

    <prefix>   ->   {
        "NAME": "root value",
        "<organisation>/NAME": "...",
        "<organisation>/<project>/<environment>/<service>/NAME": "...",
    }

Secrets Manager bills per secret, so this is the cheapest layout. Names cannot contain ``/``,
so every key splits unambiguously into a level and a variable name. The trade-offs: writes are
read-modify-write on the single secret, so two concurrent writers anywhere in the store can
overwrite each other's changes (last write wins), and the whole store must fit into one secret
value (``MAX_SECRET_SIZE`` bytes).
"""

import json

from environment_store.core.abstract_adapter import AbstractAdapter
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

from ..hierarchy import child_names, level_segments, validate_segment
from .secrets_manager import SecretsManager

# Maximum size of a secret value accepted by AWS Secrets Manager
MAX_SECRET_SIZE = 65536


class SecretsManagerAdapter(AbstractAdapter):
    """
    Store environment variables in AWS Secrets Manager, all in a single secret.

    :param region: The AWS region to use. Ignored if ``secrets_manager`` is given.
    :param prefix: Name of the secret holding the store (e.g. ``"myapp/config"``). Use different
        prefixes to keep several stores apart.
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
        prefix_segments = [
            validate_segment(s, "prefix") for s in prefix.strip("/").split("/") if s
        ]
        if not prefix_segments:
            raise ValueError("prefix must not be empty")
        self.secret_name = "/".join(prefix_segments)

    @staticmethod
    def _key(segments: list[str], name: str) -> str:
        return "/".join(segments + [name])

    def _load(self) -> dict[str, str]:
        """Return all variables of the store, keyed by their path below the prefix."""
        raw = self.secrets_manager.get_secret_string(self.secret_name)
        if raw is None:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError(f"Secret {self.secret_name!r} is not a JSON object of variables")
        return data

    def _save(self, data: dict[str, str]) -> None:
        if not data:
            self.secrets_manager.delete_secret(self.secret_name)
            return
        raw = json.dumps(data, sort_keys=True)
        size = len(raw.encode("utf-8"))
        if size > MAX_SECRET_SIZE:
            raise ValueError(
                f"Secret {self.secret_name!r} would be {size} bytes, more than the "
                f"{MAX_SECRET_SIZE} bytes Secrets Manager allows. Split the store across "
                "several prefixes."
            )
        self.secrets_manager.put_secret_string(self.secret_name, raw)

    def _level_variables(self, data: dict[str, str], segments: list[str]) -> dict[str, str]:
        """The variables stored directly at the level ``segments``."""
        result = {}
        for key, value in data.items():
            *level, name = key.split("/")
            if level == segments:
                result[name] = value
        return result

    def _levels(self) -> list[list[str]]:
        """The hierarchy path of every level that holds at least one variable."""
        return [key.split("/")[:-1] for key in self._load()]

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
        """Write all variables in a single secret update (atomic)."""
        segments = level_segments(organisation, project, environment, service)
        if not variables:
            return
        for variable in variables:
            validate_segment(variable.name, "variable name")
        data = self._load()
        data.update({self._key(segments, v.name): v.value for v in variables})
        self._save(data)

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
        return self._load().get(self._key(segments, name))

    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        segments = level_segments(organisation, project, environment, service)
        variables = self._level_variables(self._load(), segments)
        return [Variable(name=k, value=v) for k, v in variables.items()]

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
        """Delete variables; the secret is removed once the store's last variable is gone."""
        if not names:
            raise ValueError("names must not be empty")
        segments = level_segments(organisation, project, environment, service)
        for name in names:
            validate_segment(name, "variable name")
        data = self._load()
        deleted = [n for n in names if self._key(segments, n) in data]
        not_found = [n for n in names if self._key(segments, n) not in data]
        if deleted:
            for name in deleted:
                data.pop(self._key(segments, name), None)
            self._save(data)
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
