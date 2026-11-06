from collections.abc import Iterator

import pytest

from tests.adapters.postgres.server import PostgresServer, start_server


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[PostgresServer]:
    with start_server() as server:
        yield server


@pytest.fixture
def database(postgres_server: PostgresServer) -> Iterator[str]:
    """A fresh, empty database for one test."""
    with postgres_server.database() as name:
        yield name
