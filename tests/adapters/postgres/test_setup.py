import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Final

import pytest
from psycopg import sql

from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.adapters.postgres.url import parse_url
from environment_store.adapters.sql.migrations import POSTGRES_MIGRATIONS, Migration
from environment_store.core.adapter import MigratableAdapter, MigrationReport, SetupMode
from environment_store.core.errors import (
    DatabaseNotCleanError,
    SchemaOutdatedError,
    SchemaTooNewError,
    ValidationError,
)
from environment_store.core.models import StoreRecord
from tests.adapters.postgres.server import PostgresServer

pytestmark = pytest.mark.postgres

_T0: Final = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_V2: Final = Migration(
    version=2, statements=("CREATE INDEX stores_updated_at ON {schema}.stores (updated_at)",)
)
_WITH_V2: Final = (*POSTGRES_MIGRATIONS, _V2)


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


def _objects(server: PostgresServer, database: str, schema: str) -> set[str]:
    rows = server.query(
        database,
        sql.SQL(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = {}"
        ).format(sql.Literal(schema)),
    )
    return {str(row[0]) for row in rows}


def _meta(server: PostgresServer, database: str, schema: str) -> dict[str, str]:
    rows = server.query(
        database, sql.SQL("SELECT key, value FROM {}.meta").format(sql.Identifier(schema))
    )
    return {str(key): str(value) for key, value in rows}


def _open(
    server: PostgresServer,
    database: str,
    *,
    schema: str = "environment_store",
    setup: SetupMode = SetupMode.AUTO,
    migrations: tuple[Migration, ...] = POSTGRES_MIGRATIONS,
) -> PostgresAdapter:
    target = parse_url(server.url(database, schema=schema))
    return PostgresAdapter(target, setup=setup, migrations=migrations)


# --- first setup -------------------------------------------------------------------------------


def test_auto_open_creates_the_default_schema_with_version_one(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        assert adapter.list_stores() == []

    assert "environment_store" in _schemas(postgres_server, database)
    assert {"meta", "stores"} <= _objects(postgres_server, database, "environment_store")
    assert _meta(postgres_server, database, "environment_store") == {
        "app": "environment-store",
        "schema_version": "1",
    }


def test_auto_open_uses_an_existing_empty_schema(
    postgres_server: PostgresServer, database: str
) -> None:
    postgres_server.execute(database, sql.SQL("CREATE SCHEMA team_a"))

    with open_postgres(postgres_server.url(database, schema="team_a")) as adapter:
        adapter.create_store(_record())

    assert {"meta", "stores"} <= _objects(postgres_server, database, "team_a")


def test_auto_open_leaves_the_rest_of_the_database_alone(
    postgres_server: PostgresServer, database: str
) -> None:
    postgres_server.execute(
        database,
        sql.SQL("CREATE TABLE public.meta (key TEXT, value TEXT)"),
        sql.SQL("INSERT INTO public.meta VALUES ('app', 'other')"),
    )

    with open_postgres(postgres_server.url(database)) as adapter:
        adapter.create_store(_record())

    assert _objects(postgres_server, database, "public") == {"meta"}
    assert postgres_server.query(database, sql.SQL("SELECT * FROM public.meta")) == [
        ("app", "other")
    ]


def test_racing_first_opens_all_succeed(postgres_server: PostgresServer, database: str) -> None:
    url = postgres_server.url(database, schema="raced")
    racers = 8
    barrier = threading.Barrier(racers, timeout=30)

    def open_and_list() -> int:
        barrier.wait()
        with open_postgres(url) as adapter:
            return len(adapter.list_stores())

    with ThreadPoolExecutor(max_workers=racers) as pool:
        results = [pool.submit(open_and_list) for _ in range(racers)]

        assert [result.result(timeout=30) for result in results] == [0] * racers


@pytest.mark.parametrize("schema", ["select", "user", "order", "_", "public_2"])
def test_schema_names_that_are_sql_keywords_are_quoted(
    postgres_server: PostgresServer, database: str, schema: str
) -> None:
    with open_postgres(postgres_server.url(database, schema=schema)) as adapter:
        adapter.create_store(_record())
        assert adapter.read_store("base") == _record()

    assert {"meta", "stores"} <= _objects(postgres_server, database, schema)


# --- isolation -----------------------------------------------------------------------------------


def test_two_schemas_in_one_database_are_independent(
    postgres_server: PostgresServer, database: str
) -> None:
    with (
        open_postgres(postgres_server.url(database, schema="a")) as first,
        open_postgres(postgres_server.url(database, schema="b")) as second,
    ):
        first.create_store(_record("base"))
        second.create_store(_record("other"))
        second.create_store(_record("base"))
        second.delete_store("base")

        assert [info.name for info in first.list_stores()] == ["base"]
        assert [info.name for info in second.list_stores()] == ["other"]


# --- foreign content -----------------------------------------------------------------------------

_FOREIGN_CONTENT: Final[dict[str, tuple[str, ...]]] = {
    "table": ("CREATE TABLE {schema}.customers (id INT)",),
    "view": ("CREATE VIEW {schema}.v AS SELECT 1 AS one",),
    "sequence": ("CREATE SEQUENCE {schema}.seq",),
    "function": ("CREATE FUNCTION {schema}.f() RETURNS INT LANGUAGE SQL AS 'SELECT 1'",),
    "enum-type": ("CREATE TYPE {schema}.mood AS ENUM ('ok')",),
    "domain": ("CREATE DOMAIN {schema}.positive AS INT CHECK (VALUE > 0)",),
    "shell-type": ("CREATE TYPE {schema}.shell",),
    "range-type": ("CREATE TYPE {schema}.span AS RANGE (SUBTYPE = int4)",),
    "collation": ("CREATE COLLATION {schema}.c1 (provider = libc, locale = 'C')",),
    "operator": (
        "CREATE OPERATOR {schema}.=== (LEFTARG = int4, RIGHTARG = int4, "
        "FUNCTION = pg_catalog.int4eq)",
    ),
    "operator-family": ("CREATE OPERATOR FAMILY {schema}.f USING btree",),
    "operator-class": (
        "CREATE OPERATOR CLASS {schema}.oc FOR TYPE int4 USING hash AS "
        "OPERATOR 1 pg_catalog.= (int4, int4), FUNCTION 1 pg_catalog.hashint4(int4)",
    ),
    "conversion": (
        "CREATE CONVERSION {schema}.conv FOR 'LATIN1' TO 'UTF8' FROM pg_catalog.iso8859_1_to_utf8",
    ),
    "text-search-configuration": (
        "CREATE TEXT SEARCH CONFIGURATION {schema}.ts (COPY = pg_catalog.simple)",
    ),
    "text-search-dictionary": (
        "CREATE TEXT SEARCH DICTIONARY {schema}.d (TEMPLATE = pg_catalog.simple)",
    ),
    "text-search-template": (
        "CREATE TEXT SEARCH TEMPLATE {schema}.t (LEXIZE = pg_catalog.dsimple_lexize)",
    ),
    "text-search-parser": (
        "CREATE TEXT SEARCH PARSER {schema}.p (START = pg_catalog.prsd_start, "
        "GETTOKEN = pg_catalog.prsd_nexttoken, END = pg_catalog.prsd_end, "
        "LEXTYPES = pg_catalog.prsd_lextype)",
    ),
    "statistics": (
        "CREATE TABLE public.stat_source (a INT, b INT)",
        "CREATE STATISTICS {schema}.st ON a, b FROM public.stat_source",
    ),
    "meta-of-another-app": (
        "CREATE TABLE {schema}.meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "INSERT INTO {schema}.meta VALUES ('app', 'other'), ('schema_version', '1')",
    ),
    "meta-with-other-columns": ("CREATE TABLE {schema}.meta (id INT, name TEXT)",),
    "meta-with-bad-version": (
        "CREATE TABLE {schema}.meta (key TEXT PRIMARY KEY, value TEXT)",
        "INSERT INTO {schema}.meta VALUES ('app', 'environment-store'), ('schema_version', 'one')",
    ),
    "meta-with-null-values": (
        "CREATE TABLE {schema}.meta (key TEXT, value TEXT)",
        "INSERT INTO {schema}.meta VALUES ('app', NULL), (NULL, 'x')",
    ),
    "meta-is-a-view": (
        "CREATE VIEW {schema}.meta AS SELECT 'app'::text AS key, "
        "'environment-store'::text AS value",
    ),
}


def _create_foreign(server: PostgresServer, database: str, content: tuple[str, ...]) -> None:
    server.execute(
        database,
        sql.SQL("CREATE SCHEMA foreign_s"),
        *(
            sql.SQL(statement).format(schema=sql.Identifier("foreign_s"))  # ty: ignore[invalid-argument-type] - constant test DDL
            for statement in content
        ),
    )


@pytest.mark.parametrize("content", _FOREIGN_CONTENT.values(), ids=_FOREIGN_CONTENT.keys())
def test_auto_open_refuses_a_foreign_schema_and_changes_nothing(
    postgres_server: PostgresServer, database: str, content: tuple[str, ...]
) -> None:
    _create_foreign(postgres_server, database, content)
    before = _objects(postgres_server, database, "foreign_s")

    with pytest.raises(DatabaseNotCleanError, match="foreign_s"):
        open_postgres(postgres_server.url(database, schema="foreign_s"))

    assert _objects(postgres_server, database, "foreign_s") == before


def test_migrate_refuses_a_foreign_schema(postgres_server: PostgresServer, database: str) -> None:
    _create_foreign(postgres_server, database, _FOREIGN_CONTENT["table"])
    url = postgres_server.url(database, schema="foreign_s")

    with open_postgres(url, setup=SetupMode.NONE) as adapter, pytest.raises(DatabaseNotCleanError):
        adapter.migrate()

    assert _objects(postgres_server, database, "foreign_s") == {"customers"}


# --- setup mode NONE and migrate() ---------------------------------------------------------------


def test_none_open_does_not_inspect_or_create(
    postgres_server: PostgresServer, database: str
) -> None:
    _create_foreign(postgres_server, database, _FOREIGN_CONTENT["table"])

    open_postgres(postgres_server.url(database, schema="fresh"), setup=SetupMode.NONE).close()
    open_postgres(postgres_server.url(database, schema="foreign_s"), setup=SetupMode.NONE).close()

    assert "fresh" not in _schemas(postgres_server, database)
    assert _objects(postgres_server, database, "foreign_s") == {"customers"}


def test_none_open_runs_the_auto_check_before_the_first_data_operation(
    postgres_server: PostgresServer, database: str
) -> None:
    _create_foreign(postgres_server, database, _FOREIGN_CONTENT["table"])

    with open_postgres(
        postgres_server.url(database, schema="foreign_s"), setup=SetupMode.NONE
    ) as adapter:
        with pytest.raises(DatabaseNotCleanError):
            adapter.list_stores()
        with pytest.raises(DatabaseNotCleanError):
            adapter.read_store("base")


def test_none_open_creates_an_empty_schema_lazily(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database, schema="lazy"), setup=SetupMode.NONE) as a:
        assert "lazy" not in _schemas(postgres_server, database)
        a.create_store(_record())

        assert a.read_store("base") == _record()
    assert "lazy" in _schemas(postgres_server, database)


def test_migrate_creates_an_empty_schema(postgres_server: PostgresServer, database: str) -> None:
    with open_postgres(postgres_server.url(database), setup=SetupMode.NONE) as adapter:
        report = adapter.migrate()

        assert report == MigrationReport(from_version=None, to_version=1, created=True)
        assert adapter.list_stores() == []
    assert _meta(postgres_server, database, "environment_store")["schema_version"] == "1"


def test_migrate_on_a_current_schema_does_nothing(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        adapter.create_store(_record())

        report = adapter.migrate()

        assert report == MigrationReport(from_version=1, to_version=1, created=False)
        assert adapter.read_store("base") == _record()


def test_adapter_is_migratable(postgres_server: PostgresServer, database: str) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        assert isinstance(adapter, MigratableAdapter)


# --- versions ------------------------------------------------------------------------------------


def test_auto_open_refuses_an_outdated_schema_with_the_migrate_hint(
    postgres_server: PostgresServer, database: str
) -> None:
    with _open(postgres_server, database) as adapter:
        adapter.create_store(_record())

    with pytest.raises(SchemaOutdatedError, match="environment-store migrate"):
        _open(postgres_server, database, migrations=_WITH_V2)

    assert _meta(postgres_server, database, "environment_store")["schema_version"] == "1"
    assert "stores_updated_at" not in _objects(postgres_server, database, "environment_store")


def test_none_open_on_an_outdated_schema_refuses_data_operations(
    postgres_server: PostgresServer, database: str
) -> None:
    _open(postgres_server, database).close()

    with (
        _open(postgres_server, database, setup=SetupMode.NONE, migrations=_WITH_V2) as adapter,
        pytest.raises(SchemaOutdatedError),
    ):
        adapter.list_stores()


def test_migrate_upgrades_an_outdated_schema_and_keeps_the_stores(
    postgres_server: PostgresServer, database: str
) -> None:
    with _open(postgres_server, database) as adapter:
        adapter.create_store(_record())

    with _open(postgres_server, database, setup=SetupMode.NONE, migrations=_WITH_V2) as adapter:
        report = adapter.migrate()

        assert report == MigrationReport(from_version=1, to_version=2, created=False)
        assert adapter.read_store("base") == _record()
    assert _meta(postgres_server, database, "environment_store")["schema_version"] == "2"
    assert "stores_updated_at" in _objects(postgres_server, database, "environment_store")
    with _open(postgres_server, database, migrations=_WITH_V2) as upgraded:
        assert upgraded.read_store("base") == _record()


def test_migrate_creates_an_empty_schema_at_the_latest_version(
    postgres_server: PostgresServer, database: str
) -> None:
    with _open(postgres_server, database, setup=SetupMode.NONE, migrations=_WITH_V2) as adapter:
        assert adapter.migrate() == MigrationReport(from_version=None, to_version=2, created=True)

    assert _meta(postgres_server, database, "environment_store")["schema_version"] == "2"


def test_a_newer_schema_is_refused_on_open_and_by_migrate(
    postgres_server: PostgresServer, database: str
) -> None:
    _open(postgres_server, database, migrations=_WITH_V2).close()

    with pytest.raises(SchemaTooNewError, match="upgrade environment-store"):
        _open(postgres_server, database)
    with (
        _open(postgres_server, database, setup=SetupMode.NONE) as adapter,
        pytest.raises(SchemaTooNewError),
    ):
        adapter.migrate()
    assert _meta(postgres_server, database, "environment_store")["schema_version"] == "2"


@pytest.mark.parametrize(
    "migrations",
    [(), (_V2,), (POSTGRES_MIGRATIONS[0], POSTGRES_MIGRATIONS[0])],
    ids=["none", "gap", "duplicate"],
)
def test_migrations_not_numbered_one_to_n_are_rejected_before_connecting(
    migrations: tuple[Migration, ...],
) -> None:
    # An unreachable host: a connection attempt would raise BackendError instead.
    target = parse_url("postgresql://nobody@host.invalid/db")

    with pytest.raises(ValidationError, match="numbered"):
        PostgresAdapter(target, migrations=migrations)
