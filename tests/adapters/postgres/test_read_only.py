"""`SetupMode.READ_ONLY` on PostgreSQL: no setup, no writes, a short connect timeout (D54)."""

import socket
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from psycopg import sql

from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.adapters.postgres.adapter import READ_ONLY_CONNECT_TIMEOUT
from environment_store.adapters.postgres.url import parse_url
from environment_store.adapters.sql.migrations import POSTGRES_MIGRATIONS, Migration
from environment_store.core.adapter import SetupMode
from environment_store.core.errors import BackendError, SchemaOutdatedError, StoreNotFoundError
from environment_store.core.models import StoreRecord
from tests.adapters.postgres.server import PostgresServer

pytestmark = pytest.mark.postgres

_RO: Final = SetupMode.READ_ONLY
_T0: Final = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_V2: Final = Migration(
    version=2, statements=("CREATE INDEX stores_updated_at ON {schema}.stores (updated_at)",)
)


def _record(name: str = "base") -> StoreRecord:
    return StoreRecord.plain(name=name, variables={"HOST": "localhost"}, created_at=_T0)


def _schemas(server: PostgresServer, database: str) -> set[str]:
    rows = server.query(
        database,
        sql.SQL(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema'"
        ),
    )
    return {str(row[0]) for row in rows}


@pytest.fixture
def silent_server() -> Iterator[int]:
    """A local port that accepts TCP connections but never answers, like a hung server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        yield listener.getsockname()[1]


def test_read_only_on_a_database_without_the_schema_finds_no_stores_and_creates_nothing(
    postgres_server: PostgresServer, database: str
) -> None:
    before = _schemas(postgres_server, database)

    with open_postgres(postgres_server.url(database), setup=_RO) as adapter:
        assert adapter.list_stores() == []
        with pytest.raises(StoreNotFoundError):
            adapter.read_store("base")

    assert _schemas(postgres_server, database) == before


def test_read_only_on_an_empty_schema_finds_no_stores_and_creates_no_tables(
    postgres_server: PostgresServer, database: str
) -> None:
    postgres_server.execute(database, sql.SQL("CREATE SCHEMA environment_store"))

    with open_postgres(postgres_server.url(database), setup=_RO) as adapter:
        assert adapter.list_stores() == []

    tables = postgres_server.query(
        database,
        sql.SQL("SELECT count(*) FROM pg_tables WHERE schemaname = 'environment_store'"),
    )
    assert tables == [(0,)]


def test_read_only_reads_a_current_schema(postgres_server: PostgresServer, database: str) -> None:
    with open_postgres(postgres_server.url(database)) as writer:
        writer.create_store(_record())

    with open_postgres(postgres_server.url(database), setup=_RO) as adapter:
        assert [info.name for info in adapter.list_stores()] == ["base"]
        assert adapter.read_store("base") == _record()


def test_read_only_refuses_an_outdated_schema(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database)) as writer:
        writer.create_store(_record())
    target = parse_url(postgres_server.url(database))

    with (
        PostgresAdapter(target, setup=_RO, migrations=(*POSTGRES_MIGRATIONS, _V2)) as adapter,
        pytest.raises(SchemaOutdatedError),
    ):
        adapter.list_stores()


def test_read_only_refuses_migrate_and_creates_nothing(
    postgres_server: PostgresServer, database: str
) -> None:
    before = _schemas(postgres_server, database)

    with (
        open_postgres(postgres_server.url(database), setup=_RO) as adapter,
        pytest.raises(BackendError, match="read-only"),
    ):
        adapter.migrate()

    assert _schemas(postgres_server, database) == before


def test_read_only_gives_up_on_a_server_that_does_not_answer(silent_server: int) -> None:
    url = f"postgresql://nobody@127.0.0.1:{silent_server}/db?connect_timeout=60"
    started = time.monotonic()

    with pytest.raises(BackendError, match="cannot connect"):
        open_postgres(url, setup=_RO)

    assert time.monotonic() - started < READ_ONLY_CONNECT_TIMEOUT + 3


def test_read_only_lost_connection_before_the_first_read_raises_backend_error(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database), setup=_RO) as adapter:
        postgres_server.execute(
            database,
            sql.SQL(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = {} AND pid <> pg_backend_pid()"
            ).format(sql.Literal(database)),
        )

        with pytest.raises(BackendError, match="checking the schema"):
            adapter.list_stores()
