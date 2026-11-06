"""`envs migrate` (D11, D13, PD 22)."""

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Final

import pytest
import typer

from environment_store.adapters.sql.migrations import (
    POSTGRES_MIGRATIONS,
    SQLITE_MIGRATIONS,
    Migration,
)
from environment_store.adapters.sqlite import SqliteAdapter
from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.state import get_state
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.library.store import AdapterOpener
from tests.support.cli import CliHarness, assert_exit, cli_harness

_SQLITE_NEWER: Final = (
    *SQLITE_MIGRATIONS,
    Migration(version=2, statements=("CREATE TABLE extra (x INTEGER)",)),
)
_POSTGRES_NEWER: Final = (
    *POSTGRES_MIGRATIONS,
    Migration(
        version=2, statements=("CREATE INDEX stores_updated_at ON {schema}.stores (updated_at)",)
    ),
)


def _app_with_listing() -> typer.Typer:
    app = build_app()

    @app.command("list", cls=EnvsCommand)
    def listing(ctx: typer.Context) -> None:
        get_state(ctx).open_store(ctx).list_stores()

    return app


@pytest.fixture
def cli_sqlite(tmp_path: Path) -> Generator[CliHarness]:
    with cli_harness(tmp_path, "sqlite") as harness:
        yield harness


def _database(cli: CliHarness) -> Path:
    return cli.root / "envs.db"


def _newer_sqlite(cli: CliHarness) -> AdapterOpener:
    def opener(_connection: str, setup: SetupMode) -> Adapter:
        return SqliteAdapter(_database(cli), setup=setup, migrations=_SQLITE_NEWER)

    return opener


def test_migrate_creates_the_schema_of_a_new_database(cli_sqlite: CliHarness) -> None:
    result = cli_sqlite.invoke("migrate")

    assert_exit(result, 0)
    assert result.stderr == "created schema v1\n"
    assert result.stdout == ""
    assert _database(cli_sqlite).is_file()


def test_migrate_on_a_current_schema_reports_it_is_up_to_date(cli_sqlite: CliHarness) -> None:
    cli_sqlite.store().create_store("a")

    result = cli_sqlite.invoke("migrate")

    assert_exit(result, 0)
    assert result.stderr == "schema is up to date (v1)\n"
    assert [info.name for info in cli_sqlite.store().list_stores()] == ["a"]


def test_migrate_upgrades_an_outdated_schema(cli_sqlite: CliHarness) -> None:
    cli_sqlite.store().create_store("a")
    cli_sqlite.close()

    result = cli_sqlite.invoke("migrate", opener=_newer_sqlite(cli_sqlite))

    assert_exit(result, 0)
    assert result.stderr == "upgraded schema from v1 to v2\n"


def test_migrate_refuses_a_newer_schema(cli_sqlite: CliHarness) -> None:
    # Opening creates nothing (D43): the newer schema is written by an explicit migrate.
    with SqliteAdapter(_database(cli_sqlite), migrations=_SQLITE_NEWER) as newer:
        newer.migrate()

    result = cli_sqlite.invoke("migrate")

    assert_exit(result, 1)
    assert "newer" in result.stderr


def test_migrate_refuses_a_foreign_database_and_leaves_it_unchanged(
    cli_sqlite: CliHarness,
) -> None:
    path = _database(cli_sqlite)
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE users (id INTEGER)")
    connection.close()
    before = path.read_bytes()

    result = cli_sqlite.invoke("migrate")

    assert_exit(result, 1)
    assert result.stderr.startswith("Error:")
    assert path.read_bytes() == before


def test_migrate_on_a_file_backend_exits_with_one(cli_json: CliHarness) -> None:
    result = cli_json.invoke("migrate")

    assert_exit(result, 1)
    assert "no schema to migrate" in result.stderr


@pytest.mark.postgres
def test_postgres_outdated_schema_is_refused_by_a_command_and_upgraded_by_migrate(
    cli_json: CliHarness,
) -> None:
    # Imported here: psycopg and the throwaway server only for this marked test.
    from environment_store.adapters.postgres import PostgresAdapter  # noqa: PLC0415
    from environment_store.adapters.postgres.url import parse_url  # noqa: PLC0415
    from tests.adapters.postgres.server import start_server  # noqa: PLC0415

    def newer(connection: str, setup: SetupMode) -> Adapter:
        return PostgresAdapter(parse_url(connection), setup=setup, migrations=_POSTGRES_NEWER)

    with start_server() as server, server.database() as database:
        cli_json.connection = server.url(database)
        created = cli_json.invoke("migrate")
        refused = cli_json.invoke("list", app=_app_with_listing(), opener=newer)
        upgraded = cli_json.invoke("migrate", opener=newer)

    assert_exit(created, 0)
    assert_exit(refused, 1)
    assert "migrate" in refused.stderr
    assert_exit(upgraded, 0)
    assert upgraded.stderr == "upgraded schema from v1 to v2\n"
