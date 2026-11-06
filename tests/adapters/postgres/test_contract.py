from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import override

import pytest

from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.core.adapter import SetupMode
from tests.adapters.postgres.server import PostgresServer
from tests.contract.adapter_contract import AdapterContract, BackendFactory

pytestmark = pytest.mark.postgres


@dataclass(frozen=True, slots=True)
class PostgresBackend:
    url: str

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> PostgresAdapter:
        return open_postgres(self.url, setup=setup)


class TestPostgresContract(AdapterContract):
    @pytest.fixture(scope="class")
    @classmethod
    @override
    def make_backend(cls, postgres_server: PostgresServer) -> BackendFactory:
        # A fresh database per test and per Hypothesis example (IMPLEMENTATION-PLAN.md §5 A3),
        # used through the default schema `environment_store`.
        @contextmanager
        def backend() -> Generator[PostgresBackend]:
            with postgres_server.database() as database:
                yield PostgresBackend(postgres_server.url(database))

        return backend
