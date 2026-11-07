from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Final

import psycopg
import pytest
from psycopg import sql

from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.adapters.postgres.url import PostgresTarget
from environment_store.core.adapter import SetupMode
from environment_store.core.errors import BackendError, SetupPrivilegeError, ValidationError
from environment_store.core.models import StoreRecord
from tests.adapters.postgres.server import PostgresServer

pytestmark = pytest.mark.postgres

_T0: Final = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_RECORD: Final = StoreRecord.plain(name="base", variables={"HOST": "localhost"}, created_at=_T0)


def _schemas(server: PostgresServer, database: str) -> set[str]:
    rows = server.query(database, sql.SQL("SELECT nspname FROM pg_namespace"))
    return {str(row[0]) for row in rows}


@pytest.fixture
def role(postgres_server: PostgresServer) -> Iterator[tuple[str, str]]:
    with postgres_server.role() as created:
        yield created


@pytest.fixture
def database(postgres_server: PostgresServer, role: tuple[str, str]) -> Iterator[str]:
    # Overrides the shared fixture: created after the role, so it is dropped (with the role's
    # grants in it) before the role.
    del role  # only needed for the order of setup and teardown
    with postgres_server.database() as name:
        yield name


# --- missing privileges --------------------------------------------------------------------------


def test_first_setup_without_create_privilege_raises_with_the_migrate_hint(
    postgres_server: PostgresServer, database: str, role: tuple[str, str]
) -> None:
    user, password = role
    url = postgres_server.url(database, user=user, password=password)

    with pytest.raises(SetupPrivilegeError, match="environment-store migrate") as caught:
        open_postgres(url)

    assert password not in str(caught.value)
    assert "environment_store" not in _schemas(postgres_server, database)


def test_first_setup_in_a_schema_without_create_privilege_raises_the_hint(
    postgres_server: PostgresServer, database: str, role: tuple[str, str]
) -> None:
    user, password = role
    postgres_server.execute(
        database,
        sql.SQL("CREATE SCHEMA team"),
        sql.SQL("GRANT USAGE ON SCHEMA team TO {}").format(sql.Identifier(user)),
    )

    with pytest.raises(SetupPrivilegeError, match="migrate"):
        open_postgres(postgres_server.url(database, schema="team", user=user, password=password))


def test_after_an_admin_ran_migrate_a_user_without_create_privilege_works(
    postgres_server: PostgresServer, database: str, role: tuple[str, str]
) -> None:
    user, password = role
    with open_postgres(postgres_server.url(database), setup=SetupMode.NONE) as admin:
        admin.migrate()
    postgres_server.execute(
        database,
        sql.SQL("GRANT USAGE ON SCHEMA environment_store TO {}").format(sql.Identifier(user)),
        sql.SQL(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA environment_store TO {}"
        ).format(sql.Identifier(user)),
    )

    with open_postgres(postgres_server.url(database, user=user, password=password)) as adapter:
        adapter.create_store(_RECORD)

        assert adapter.read_store("base") == _RECORD


def test_a_user_who_may_not_read_the_schema_gets_the_privilege_hint(
    postgres_server: PostgresServer, database: str, role: tuple[str, str]
) -> None:
    user, password = role
    open_postgres(postgres_server.url(database)).close()
    postgres_server.execute(
        database,
        sql.SQL("GRANT USAGE ON SCHEMA environment_store TO {}").format(sql.Identifier(user)),
    )

    with pytest.raises(SetupPrivilegeError, match="privilege"):
        open_postgres(postgres_server.url(database, user=user, password=password))


# --- identifier injection ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema",
    [
        "x%22%3B%20DROP%20SCHEMA%20public%20CASCADE%3B%20--",
        "public.stores",
        "x%3Bdrop",
        "Upper",
        "a%2Fb",
        "1x",
        "x" * 64,
    ],
)
def test_injected_schema_names_are_rejected_before_connecting(
    postgres_server: PostgresServer, database: str, schema: str
) -> None:
    before = _schemas(postgres_server, database)

    with pytest.raises(ValidationError, match="schema"):
        open_postgres(postgres_server.url(database, schema=schema))

    assert _schemas(postgres_server, database) == before


def test_store_names_are_parameters_not_sql(postgres_server: PostgresServer, database: str) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        adapter.create_store(_RECORD)

        with pytest.raises(ValidationError):
            adapter.read_store("base' OR '1'='1")
        with pytest.raises(ValidationError):
            adapter.delete_store("x'; DELETE FROM environment_store.stores; --")

        assert adapter.read_store("base") == _RECORD


# --- no credentials in errors --------------------------------------------------------------------

_PASSWORD: Final = "pw-9f3a-never-shown"  # noqa: S105 - test value that must never show


def test_connection_failure_raises_backend_error_without_the_password(
    postgres_server: PostgresServer,
) -> None:
    url = postgres_server.url("no_such_database", user="postgres", password=_PASSWORD)

    with pytest.raises(BackendError, match="no_such_database") as caught:
        open_postgres(url)

    assert _PASSWORD not in str(caught.value)
    assert _PASSWORD not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://u:{_PASSWORD}%zz@host.invalid:1/db",
        f"postgresql://host.invalid:1/db?password={_PASSWORD}%zz",
    ],
    ids=["userinfo", "query"],
)
def test_driver_errors_quoting_the_password_are_not_chained(url: str) -> None:
    # libpq rejects the escape before connecting and quotes the whole token.
    with pytest.raises(BackendError, match="percent") as caught:
        open_postgres(url)

    assert _PASSWORD not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_hand_built_target_the_driver_cannot_decode_raises_backend_error() -> None:
    target = PostgresTarget(
        conninfo=f"postgresql://u:{_PASSWORD}%F2@host.invalid:1/db",
        schema="s",
        location="l",
        secrets=(f"{_PASSWORD}%F2",),
    )

    with pytest.raises(BackendError, match="UTF-8") as caught:
        PostgresAdapter(target)

    assert _PASSWORD not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_connection_failure_with_the_password_in_the_query_hides_it(
    postgres_server: PostgresServer,
) -> None:
    url = postgres_server.url("no_such_database", query=f"password={_PASSWORD}")

    with pytest.raises(BackendError) as caught:
        open_postgres(url)

    assert _PASSWORD not in str(caught.value)


def test_connection_errors_never_echo_the_client_key_passphrase() -> None:
    # libpq rejects the malformed escape while parsing, before any connection attempt, and
    # quotes the sslpassword value; TEST-NET host, so nothing could be reached anyway.
    url = "postgresql://u@203.0.113.1:1/db?connect_timeout=1&sslpassword=TopSecret%zz"

    with pytest.raises(BackendError) as caught:
        open_postgres(url, setup=SetupMode.NONE)

    assert "TopSecret" not in str(caught.value)
    assert "***" in str(caught.value)


def test_redaction_covers_driver_messages_that_echo_the_password(
    postgres_server: PostgresServer,
) -> None:
    # libpq echoes an invalid option value; here the "password" is that value.
    url = postgres_server.url("postgres", query=f"sslmode={_PASSWORD}&password={_PASSWORD}")

    with pytest.raises(BackendError) as caught:
        open_postgres(url)

    assert _PASSWORD not in str(caught.value)
    assert "***" in str(caught.value)


def _drop_stores(server: PostgresServer, database: str) -> None:
    server.execute(database, sql.SQL("DROP TABLE environment_store.stores"))


_OPERATIONS: Final[dict[str, Callable[[PostgresAdapter], object]]] = {
    "list": lambda adapter: adapter.list_stores(),
    "create": lambda adapter: adapter.create_store(_RECORD),
    "read": lambda adapter: adapter.read_store("base"),
    "write": lambda adapter: adapter.write_store(
        StoreRecord.plain(name="base", variables={}, revision=2, created_at=_T0),
        expected_revision=1,
    ),
    "delete": lambda adapter: adapter.delete_store("base"),
}


@pytest.mark.parametrize("operation", _OPERATIONS.values(), ids=_OPERATIONS.keys())
def test_driver_errors_become_backend_errors_naming_the_location(
    postgres_server: PostgresServer,
    database: str,
    operation: Callable[[PostgresAdapter], object],
) -> None:
    with postgres_server.owner_role(database) as (user, password):
        url = postgres_server.url(database, user=user, password=password)
        with open_postgres(url) as adapter:
            _drop_stores(postgres_server, database)

            with pytest.raises(BackendError, match="environment_store") as caught:
                operation(adapter)

    assert "SQLSTATE 42P01" in str(caught.value)
    assert password not in str(caught.value)
    assert caught.value.__cause__ is not None


def test_migrate_on_a_closed_adapter_raises_backend_error(
    postgres_server: PostgresServer, database: str
) -> None:
    adapter = open_postgres(postgres_server.url(database))
    adapter.close()

    with pytest.raises(BackendError, match="closed"):
        adapter.migrate()


def test_lost_connection_raises_backend_error(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        postgres_server.execute(
            database,
            sql.SQL(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = {} AND pid <> pg_backend_pid()"
            ).format(sql.Literal(database)),
        )

        with pytest.raises(BackendError, match="57P01"):
            adapter.list_stores()
        # The driver now refuses on its own, without a server error code.
        with pytest.raises(BackendError, match="connection") as caught:
            adapter.read_store("base")

        assert "SQLSTATE" not in str(caught.value)
        # Client-side driver text is redacted, so the raw exception is not kept.
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None


def test_unexpected_driver_error_during_setup_raises_backend_error(
    postgres_server: PostgresServer, database: str
) -> None:
    open_postgres(postgres_server.url(database)).close()
    url = postgres_server.url(database, query="options=-c%20lock_timeout%3D100")
    with psycopg.connect(postgres_server.url(database)) as blocker:
        # Holds the lock until the end of the block, so the setup cannot read meta in time.
        blocker.execute("LOCK TABLE environment_store.meta IN ACCESS EXCLUSIVE MODE")

        with pytest.raises(BackendError, match="55P03") as caught:
            open_postgres(url)

    assert not isinstance(caught.value, SetupPrivilegeError)
