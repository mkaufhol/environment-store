import json
import os

from .abstract_adapter import AbstractAdapter
from ..schemas import Variable


class JsonFileAdapter(AbstractAdapter):
    """
    Adapter for storing environment variables in a local JSON file.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def _load_data(self) -> dict:
        """Load data from the JSON file."""
        if not os.path.exists(self.file_path):
            return {}
        with open(self.file_path, "r") as f:
            content = f.read()
            if content == "":
                return {}
            return json.loads(content)

    def _save_data(self, data: dict) -> None:
        """Save data to the JSON file."""
        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=2)

    def set_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        data = self._load_data()
        if (
            service is not None
            and environment is not None
            and project is not None
            and organisation is not None
        ):
            data.setdefault(organisation, {}).setdefault(project, {}).setdefault(
                environment, {}
            ).setdefault(service, {})[name] = value
        elif environment is not None and project is not None and organisation is not None:
            data.setdefault(organisation, {}).setdefault(project, {}).setdefault(
                environment, {}
            )[name] = value
        elif project is not None and organisation is not None:
            data.setdefault(organisation, {}).setdefault(project, {})[name] = value
        elif organisation is not None:
            data.setdefault(organisation, {})[name] = value
        else:
            data[name] = value
        self._save_data(data)

    def set_variables(
        self,
        variables: list[Variable],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        for variable in variables:
            self.set_variable(
                variable.name, variable.value, organisation, project, environment, service
            )

    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        data = self._load_data()
        if (
            service is not None
            and environment is not None
            and project is not None
            and organisation is not None
        ):
            return (
                data.get(organisation, {})
                .get(project, {})
                .get(environment, {})
                .get(service, {})
                .get(name)
            )
        elif environment is not None and project is not None and organisation is not None:
            return data.get(organisation, {}).get(project, {}).get(environment, {}).get(name)
        elif project is not None and organisation is not None:
            return data.get(organisation, {}).get(project, {}).get(name)
        elif organisation is not None:
            return data.get(organisation, {}).get(name)
        else:
            return data.get(name)

    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        data = self._load_data()
        if (
            service is not None
            and environment is not None
            and project is not None
            and organisation is not None
        ):
            return [
                Variable(name=name, value=value)
                for name, value in data.get(organisation, {})
                .get(project, {})
                .get(environment, {})
                .get(service, {})
                .items()
            ]
        elif environment is not None and project is not None and organisation is not None:
            return [
                Variable(name=name, value=value)
                for name, value in data.get(organisation, {})
                .get(project, {})
                .get(environment, {})
                .items()
            ]
        elif project is not None and organisation is not None:
            return [
                Variable(name=name, value=value)
                for name, value in data.get(organisation, {}).get(project, {}).items()
            ]
        elif organisation is not None:
            return [
                Variable(name=name, value=value)
                for name, value in data.get(organisation, {}).items()
            ]
        else:
            return [Variable(name=name, value=value) for name, value in data.items()]

    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        data = self._load_data()
        if (
            service is not None
            and environment is not None
            and project is not None
            and organisation is not None
        ):
            if name in data.get(organisation, {}).get(project, {}).get(environment, {}).get(
                service, {}
            ):
                del data[organisation][project][environment][service][name]
                self._save_data(data)
                return True
            return False
        elif environment is not None and project is not None and organisation is not None:
            if name in data.get(organisation, {}).get(project, {}).get(environment, {}):
                del data[organisation][project][environment][name]
                self._save_data(data)
                return True
            return False
        elif project is not None and organisation is not None:
            if name in data.get(organisation, {}).get(project, {}):
                del data[organisation][project][name]
                self._save_data(data)
                return True
            return False
        elif organisation is not None:
            if name in data.get(organisation, {}):
                del data[organisation][name]
                self._save_data(data)
                return True
            return False
        else:
            if name in data:
                del data[name]
                self._save_data(data)
                return True
            return False

    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, list[str]]:
        deleted = []
        not_found = []
        for name in names:
            if self.delete_variable(name, organisation, project, environment, service):
                deleted.append(name)
            else:
                not_found.append(name)
        return {"deleted": deleted, "not_found": not_found}

    def get_organisations(self) -> list[str]:
        data = self._load_data()
        return [k for k, v in data.items() if isinstance(v, dict)]

    def get_projects(self, organisation: str) -> list[str]:
        data = self._load_data()
        return [k for k, v in data.get(organisation, {}).items() if isinstance(v, dict)]

    def get_environments(self, organisation: str, project: str) -> list[str]:
        data = self._load_data()
        return [
            k
            for k, v in data.get(organisation, {}).get(project, {}).items()
            if isinstance(v, dict)
        ]

    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        data = self._load_data()
        return [
            k
            for k, v in data.get(organisation, {}).get(project, {}).get(environment, {}).items()
            if isinstance(v, dict)
        ]
