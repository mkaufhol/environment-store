from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from hypothesis import given
from psycopg import sql

from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.core.adapter import SetupMode
from tests.adapters.postgres.server import PostgresServer, unique_name
from tests.contract.adapter_contract import AdapterContract, BackendFactory


@dataclass(frozen=True, slots=True)
class PostgresBackend:
    url: str

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> PostgresAdapter:
        return open_postgres(self.url, setup=setup)


def _own_property_tests[C: type[AdapterContract]](cls: C) -> C:
    """Give the class its own copy of every inherited Hypothesis test.

    Hypothesis fails a `@given` function that is called with instances of several classes
    (`HealthCheck.differing_executors`), and every adapter subclasses the same contract. A copy
    built from the original test body and strategies keeps the tests identical but separate.
    """
    for name, member in vars(AdapterContract).items():
        handle = getattr(member, "hypothesis", None)
        if handle is not None:
            # _given_kwargs: the exact strategies of the contract, so the copy cannot drift.
            setattr(cls, name, given(**handle._given_kwargs)(handle.inner_test))
    return cls


@_own_property_tests
class TestPostgresContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    def make_backend(cls, postgres_server: PostgresServer, class_database: str) -> BackendFactory:
        # A fresh schema per test and per Hypothesis example: as isolated as a fresh database
        # (the adapter only touches its own schema) and much faster.
        @contextmanager
        def backend() -> Generator[PostgresBackend]:
            schema = unique_name("s")
            try:
                yield PostgresBackend(postgres_server.url(class_database, schema=schema))
            finally:
                postgres_server.execute(
                    class_database,
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)),
                )

        return backend
