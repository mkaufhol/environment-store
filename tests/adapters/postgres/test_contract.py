from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from hypothesis import given

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


def _own_property_tests[C: type[AdapterContract]](cls: C) -> C:
    """Give the class its own copy of every inherited Hypothesis test.

    Hypothesis fails a `@given` function that is called with instances of several classes
    (`HealthCheck.differing_executors`), and every adapter subclasses the same contract. A copy
    built from the original test body and strategies keeps the tests identical but separate.

    A workaround for a defect of the shared `tests/contract/adapter_contract.py` (reported, not
    fixed here because A3 does not own it); it relies on Hypothesis internals and should go once
    the contract gives every subclass its own property tests.
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
    def make_backend(cls, postgres_server: PostgresServer) -> BackendFactory:
        # A fresh database per test and per Hypothesis example (IMPLEMENTATION-PLAN.md §5 A3),
        # used through the default schema `environment_store`.
        @contextmanager
        def backend() -> Generator[PostgresBackend]:
            with postgres_server.database() as database:
                yield PostgresBackend(postgres_server.url(database))

        return backend
