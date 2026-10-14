from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError

from environment_store.core.abstract_adapter import AbstractAdapter
from environment_store.core.exceptions import VariableExistsError, VariableNotFoundError
from environment_store.core.schemas import Variable

from . import queries

UNIQUE_VIOLATION = "23505"


class PostgreSQLAdapter(AbstractAdapter):
    """
    Adapter for storing environment variables in a PostgreSQL database.

    The database schema is managed with yoyo migrations (see the ``migrations`` directory).
    Run them before using the adapter.

    Args:
        engine: A SQLAlchemy engine, or a database URL such as
            ``postgresql+psycopg://user:password@host:5432/dbname``.
    """

    def __init__(self, engine: Engine | str):
        self.engine = create_engine(engine) if isinstance(engine, str) else engine

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Variable name must be a non-empty string")

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
        for variable in variables:
            self._validate_name(variable.name)
        with self.engine.begin() as conn:
            querier = queries.Querier(conn)
            for variable in variables:
                querier.upsert_entry(
                    queries.UpsertEntryParams(
                        organization=organisation,
                        project=project,
                        environment=environment,
                        service=service,
                        var=variable.name,
                        var_value=variable.value,
                    )
                )

    def get_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> str | None:
        with self.engine.connect() as conn:
            entry = queries.Querier(conn).get_entry(
                queries.GetEntryParams(
                    organization=organisation,
                    project=project,
                    environment=environment,
                    service=service,
                    var=name,
                )
            )
        return entry.var_value if entry is not None else None

    def get_variables(
        self,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> list[Variable]:
        with self.engine.connect() as conn:
            rows = queries.Querier(conn).get_variables(
                organization=organisation,
                project=project,
                environment=environment,
                service=service,
            )
            return [
                Variable(name=row.var, value=row.var_value or "") for row in rows if row.var
            ]

    def delete_variable(
        self,
        name: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> bool:
        deleted = self.delete_variables([name], organisation, project, environment, service)
        return name in deleted["deleted"]

    def delete_variables(
        self,
        names: list[str],
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> dict[str, list[str]]:
        deleted: list[str] = []
        not_found: list[str] = []
        with self.engine.begin() as conn:
            querier = queries.Querier(conn)
            for name in names:
                affected = querier.delete_entry(
                    queries.DeleteEntryParams(
                        organization=organisation,
                        project=project,
                        environment=environment,
                        service=service,
                        var=name,
                    )
                )
                (deleted if affected else not_found).append(name)
        return {"deleted": deleted, "not_found": not_found}

    def get_organisations(self) -> list[str]:
        with self.engine.connect() as conn:
            return [row for row in queries.Querier(conn).list_organizations() if row]

    def get_projects(self, organisation: str) -> list[str]:
        with self.engine.connect() as conn:
            return [
                row
                for row in queries.Querier(conn).list_projects(organization=organisation)
                if row
            ]

    def get_environments(self, organisation: str, project: str) -> list[str]:
        with self.engine.connect() as conn:
            return [
                row
                for row in queries.Querier(conn).list_environments(
                    organization=organisation, project=project
                )
                if row
            ]

    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        with self.engine.connect() as conn:
            return [
                row
                for row in queries.Querier(conn).list_services(
                    organization=organisation, project=project, environment=environment
                )
                if row
            ]

    def create_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        self._validate_name(name)
        try:
            with self.engine.begin() as conn:
                queries.Querier(conn).create_entry(
                    queries.CreateEntryParams(
                        organization=organisation,
                        project=project,
                        environment=environment,
                        service=service,
                        var=name,
                        var_value=value,
                        is_secret=False,
                    )
                )
        except IntegrityError as e:
            if getattr(e.orig, "sqlstate", None) == UNIQUE_VIOLATION:
                raise VariableExistsError(f"Variable '{name}' already exists") from e
            raise

    def update_variable(
        self,
        name: str,
        value: str,
        organisation: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        service: str | None = None,
    ) -> None:
        self._validate_name(name)
        with self.engine.begin() as conn:
            affected = queries.Querier(conn).update_entry(
                queries.UpdateEntryParams(
                    organization=organisation,
                    project=project,
                    environment=environment,
                    service=service,
                    var=name,
                    var_value=value,
                )
            )
        if not affected:
            raise VariableNotFoundError(f"Variable '{name}' does not exist")
