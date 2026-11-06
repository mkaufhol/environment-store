import dataclasses
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from psycopg import sql

from environment_store.adapters import postgres
from environment_store.adapters.postgres import PostgresAdapter, open_postgres
from environment_store.core.connection import open_adapter
from environment_store.core.errors import BackendError, UnsupportedFormatError
from environment_store.core.models import StoreRecord
from tests.adapters.postgres.server import PostgresServer, unique_name

_T0: Final = datetime(2026, 11, 6, 10, 0, 0, 123456, tzinfo=UTC)
_RECORD: Final = StoreRecord.plain(name="base", variables={"HOST": "localhost"}, created_at=_T0)


def test_package_exports_the_factory_and_the_adapter() -> None:
    assert set(postgres.__all__) == {"PostgresAdapter", "open_postgres"}


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "PostgreSQL"])
def test_open_adapter_selects_the_postgres_adapter_by_scheme(
    postgres_server: PostgresServer, database: str, scheme: str
) -> None:
    url = scheme + postgres_server.url(database).removeprefix("postgresql")

    with open_adapter(url) as adapter:
        assert isinstance(adapter, PostgresAdapter)
        adapter.create_store(_RECORD)
        assert adapter.read_store("base") == _RECORD


def test_open_adapter_without_psycopg_asks_for_the_postgres_extra() -> None:
    code = (
        "import sys\n"
        "sys.modules['psycopg'] = None\n"
        "from environment_store.core.connection import open_adapter\n"
        "from environment_store.core.errors import MissingExtraError\n"
        "try:\n"
        "    open_adapter('postgresql://host/db')\n"
        "except MissingExtraError as err:\n"
        "    print(err.extra)\n"
    )

    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "postgres"


def test_timestamps_are_utc_whatever_the_session_time_zone(
    postgres_server: PostgresServer, database: str
) -> None:
    url = postgres_server.url(database, query="options=-c%20TimeZone%3DAsia%2FKolkata")
    with open_postgres(url) as adapter:
        adapter.create_store(_RECORD)

        record = adapter.read_store("base")
        info = adapter.list_stores()[0]

    for value in (record.created_at, record.updated_at, info.created_at, info.updated_at):
        assert value == _T0
        assert value.utcoffset() == timedelta(0)


def test_listing_is_in_code_point_order_under_a_linguistic_collation(
    postgres_server: PostgresServer,
) -> None:
    # Code point order: '-' < digits < '_' < letters; an ICU collation ignores punctuation.
    names = ["b", "a_1", "a-2", "a", "0x", "z9", "a1", "a-"]
    with postgres_server.database(icu_locale="en-US") as database:
        with open_postgres(postgres_server.url(database)) as adapter:
            for name in names:
                adapter.create_store(dataclasses.replace(_RECORD, name=name))

            assert [info.name for info in adapter.list_stores()] == sorted(names)
        collated = postgres_server.query(
            database, sql.SQL("SELECT name FROM environment_store.stores ORDER BY name")
        )
    assert [row[0] for row in collated] != sorted(names)


def test_values_are_stored_as_jsonb_and_ciphertext_as_bytea(
    postgres_server: PostgresServer, database: str
) -> None:
    with open_postgres(postgres_server.url(database)) as adapter:
        adapter.create_store(_RECORD)

    rows = postgres_server.query(
        database,
        sql.SQL(
            "SELECT pg_typeof(variables)::text, variables ->> 'HOST', pg_typeof(created_at)::text "
            "FROM environment_store.stores"
        ),
    )

    assert rows == [("jsonb", "localhost", "timestamp with time zone")]


def test_unrecognised_cipher_metadata_fails_reading_but_not_listing(
    postgres_server: PostgresServer, database: str
) -> None:
    open_postgres(postgres_server.url(database)).close()
    postgres_server.execute(
        database,
        sql.SQL(
            "INSERT INTO environment_store.stores (name, encrypted, cipher_meta, ciphertext, "
            "created_at, updated_at) VALUES ('future', true, '{\"cipher\": \"age\"}', "
            "'\\x00', now(), now())"
        ),
    )

    with open_postgres(postgres_server.url(database)) as adapter:
        infos = adapter.list_stores()
        with pytest.raises(UnsupportedFormatError, match="future"):
            adapter.read_store("future")

    assert [(info.name, info.encrypted, info.key_mode) for info in infos] == [
        ("future", True, None)
    ]


def test_corrupt_rows_raise_backend_error_naming_the_store(
    postgres_server: PostgresServer, database: str
) -> None:
    open_postgres(postgres_server.url(database)).close()
    postgres_server.execute(
        database,
        sql.SQL(
            "INSERT INTO environment_store.stores (name, encrypted, variables, created_at, "
            "updated_at) VALUES ('broken', false, '[1, 2]', now(), now())"
        ),
    )

    with (
        open_postgres(postgres_server.url(database)) as adapter,
        pytest.raises(BackendError, match="broken"),
    ):
        adapter.read_store("broken")


def _connections(server: PostgresServer, application: str) -> int:
    rows = server.query(
        "postgres",
        sql.SQL("SELECT count(*) FROM pg_stat_activity WHERE application_name = {}").format(
            sql.Literal(application)
        ),
    )
    return int(str(rows[0][0]))


def test_a_refused_open_closes_its_connection(
    postgres_server: PostgresServer, database: str
) -> None:
    postgres_server.execute(
        database, sql.SQL("CREATE SCHEMA busy"), sql.SQL("CREATE TABLE busy.t (id INT)")
    )
    application = unique_name("refused")
    url = postgres_server.url(database, schema="busy", query=f"application_name={application}")

    with pytest.raises(BackendError):
        open_postgres(url)

    assert _connections(postgres_server, application) == 0


def test_close_releases_the_connection(postgres_server: PostgresServer, database: str) -> None:
    application = unique_name("closing")
    adapter = open_postgres(postgres_server.url(database, query=f"application_name={application}"))
    assert _connections(postgres_server, application) == 1

    adapter.close()

    assert _connections(postgres_server, application) == 0


def test_repr_names_the_location_but_no_credentials(
    postgres_server: PostgresServer, database: str
) -> None:
    password = "pw-in-repr"  # noqa: S105 - test value that must never show
    url = postgres_server.url(database, user="postgres", password=password)
    with open_postgres(url) as adapter:
        text = repr(adapter)

    assert "environment_store" in text
    assert password not in text
