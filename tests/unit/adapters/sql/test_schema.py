import re
import sqlite3
from collections.abc import Iterator
from typing import Final

import pytest
from psycopg import sql

from environment_store.adapters.sql.schema import (
    META_APP,
    META_APP_KEY,
    META_TABLE,
    META_VERSION_KEY,
    POSTGRES_CREATE_SCHEMA,
    POSTGRES_SCHEMA_V1,
    SCHEMA_VERSION,
    SQLITE_SCHEMA_V1,
    STORE_INFO_COLUMNS,
    STORES_COLUMNS,
    STORES_TABLE,
)

_TS: Final = "2026-11-06T10:00:00.000000Z"


@pytest.fixture
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in SQLITE_SCHEMA_V1:
            connection.execute(statement)
        yield connection
    finally:
        connection.close()


def _insert(connection: sqlite3.Connection, **overrides: object) -> None:
    row: dict[str, object] = {
        "name": "base",
        "encrypted": 0,
        "cipher_meta": None,
        "variables": "{}",
        "ciphertext": None,
        "revision": 1,
        "created_at": _TS,
        "updated_at": _TS,
    }
    row.update(overrides)
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO stores ({columns}) VALUES ({placeholders})",  # noqa: S608 - fixed names
        tuple(row.values()),
    )


def _tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {name for (name,) in rows}


def _sqlite_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return tuple(row[1] for row in rows)


# --- constants ---------------------------------------------------------------------------------


def test_schema_version_is_1() -> None:
    assert SCHEMA_VERSION == 1


def test_meta_marks_the_database_as_environment_store() -> None:
    assert (META_TABLE, META_APP_KEY, META_APP, META_VERSION_KEY) == (
        "meta",
        "app",
        "environment-store",
        "schema_version",
    )


def test_stores_columns_are_the_eight_columns_in_ddl_order() -> None:
    assert STORES_TABLE == "stores"
    assert STORES_COLUMNS == (
        "name",
        "encrypted",
        "cipher_meta",
        "variables",
        "ciphertext",
        "revision",
        "created_at",
        "updated_at",
    )


def test_store_info_columns_are_the_stores_columns_without_payloads() -> None:
    payloads = {"variables", "ciphertext"}

    assert tuple(column for column in STORES_COLUMNS if column not in payloads) == (
        STORE_INFO_COLUMNS
    )


# --- SQLite DDL (executed) ---------------------------------------------------------------------


def test_sqlite_schema_creates_meta_and_stores_tables(database: sqlite3.Connection) -> None:
    assert _tables(database) == {META_TABLE, STORES_TABLE}


def test_sqlite_stores_table_has_the_columns_in_ddl_order(database: sqlite3.Connection) -> None:
    assert _sqlite_columns(database, STORES_TABLE) == STORES_COLUMNS


def test_sqlite_schema_inserts_the_app_marker_and_schema_version(
    database: sqlite3.Connection,
) -> None:
    rows = dict(database.execute("SELECT key, value FROM meta").fetchall())

    assert rows == {META_APP_KEY: META_APP, META_VERSION_KEY: str(SCHEMA_VERSION)}


def test_sqlite_accepts_a_plaintext_row(database: sqlite3.Connection) -> None:
    _insert(database)

    assert database.execute("SELECT count(*) FROM stores").fetchone() == (1,)


def test_sqlite_accepts_an_encrypted_row(database: sqlite3.Connection) -> None:
    _insert(database, encrypted=1, cipher_meta="{}", variables=None, ciphertext=b"\x00\x01")

    assert database.execute("SELECT count(*) FROM stores").fetchone() == (1,)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"ciphertext": b"x"}, id="plaintext-with-ciphertext"),
        pytest.param({"cipher_meta": "{}"}, id="plaintext-with-cipher-meta"),
        pytest.param({"variables": None}, id="plaintext-without-variables"),
        pytest.param({"encrypted": 1}, id="encrypted-without-ciphertext-and-meta"),
        pytest.param(
            {"encrypted": 1, "cipher_meta": "{}", "ciphertext": b"x"},
            id="encrypted-with-variables",
        ),
        pytest.param(
            {"encrypted": 1, "variables": None, "ciphertext": b"x"},
            id="encrypted-without-cipher-meta",
        ),
        pytest.param(
            {"encrypted": 1, "variables": None, "cipher_meta": "{}"},
            id="encrypted-without-ciphertext",
        ),
        pytest.param(
            {"encrypted": 2, "variables": None, "cipher_meta": "{}", "ciphertext": b"x"},
            id="encrypted-not-0-or-1",
        ),
        pytest.param({"revision": 0}, id="revision-0"),
        pytest.param({"name": None}, id="name-null"),
        pytest.param({"encrypted": None}, id="encrypted-null"),
        pytest.param({"created_at": None}, id="created-at-null"),
        pytest.param({"updated_at": None}, id="updated-at-null"),
        pytest.param({"revision": None}, id="revision-null"),
    ],
)
def test_sqlite_check_constraints_reject_invalid_rows(
    database: sqlite3.Connection, overrides: dict[str, object]
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert(database, **overrides)


def test_sqlite_rejects_a_duplicate_store_name(database: sqlite3.Connection) -> None:
    _insert(database)

    with pytest.raises(sqlite3.IntegrityError):
        _insert(database)


def test_sqlite_revision_defaults_to_1(database: sqlite3.Connection) -> None:
    database.execute(
        "INSERT INTO stores (name, encrypted, variables, created_at, updated_at) "
        "VALUES ('base', 0, '{}', ?, ?)",
        (_TS, _TS),
    )

    assert database.execute("SELECT revision FROM stores").fetchone() == (1,)


def test_sqlite_rejects_a_duplicate_meta_key(database: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("INSERT INTO meta (key, value) VALUES ('app', 'other')")


def test_sqlite_schema_statements_are_single_statements() -> None:
    assert all(sqlite3.complete_statement(f"{statement};") for statement in SQLITE_SCHEMA_V1)
    assert not any(";" in statement for statement in SQLITE_SCHEMA_V1)


# --- PostgreSQL DDL (structural; executed by the PostgreSQL adapter tests) ---------------------


def _compose(statement: str, schema: str = "environment_store") -> str:
    return sql.SQL(statement).format(schema=sql.Identifier(schema)).as_string(None)  # ty: ignore[invalid-argument-type] - psycopg types SQL() as LiteralString; the DDL is a constant


def test_postgres_schema_has_one_statement_per_sqlite_statement() -> None:
    assert len(POSTGRES_SCHEMA_V1) == len(SQLITE_SCHEMA_V1)


def test_postgres_schema_qualifies_every_table_with_the_schema_placeholder() -> None:
    table_references = [
        match.group(1)
        for statement in POSTGRES_SCHEMA_V1
        for match in re.finditer(r"\b(?:TABLE|INTO)\s+(\S+)", statement)
    ]

    assert table_references == [
        "{schema}.meta",
        "{schema}.stores",
        "{schema}.meta",
    ]


def test_postgres_schema_composes_with_a_quoted_identifier() -> None:
    composed = [_compose(statement, 'odd"name') for statement in POSTGRES_SCHEMA_V1]

    assert composed[0].startswith('CREATE TABLE "odd""name".meta (')
    assert all("{" not in statement and "}" not in statement for statement in composed)


def test_postgres_schema_uses_native_types() -> None:
    stores = POSTGRES_SCHEMA_V1[1]

    for column_type in ("BOOLEAN", "JSONB", "BYTEA", "INTEGER", "TIMESTAMPTZ"):
        assert re.search(rf"\b{column_type}\b", stores)
    assert "BLOB" not in stores
    assert "IN (0, 1)" not in stores


def test_postgres_stores_table_declares_the_columns_in_ddl_order() -> None:
    declared = re.findall(r"^\s{4}([a-z_]+)\s+[A-Z]", POSTGRES_SCHEMA_V1[1], flags=re.MULTILINE)

    assert tuple(declared) == STORES_COLUMNS


def test_postgres_stores_table_has_the_plaintext_or_encrypted_check() -> None:
    normalised = " ".join(POSTGRES_SCHEMA_V1[1].split())

    assert (
        "CHECK ( (encrypted AND cipher_meta IS NOT NULL AND ciphertext IS NOT NULL "
        "AND variables IS NULL) OR (NOT encrypted AND cipher_meta IS NULL "
        "AND variables IS NOT NULL AND ciphertext IS NULL) )"
    ) in normalised
    assert "CHECK (revision >= 1)" in normalised


def test_postgres_schema_inserts_the_same_meta_rows_as_sqlite() -> None:
    assert POSTGRES_SCHEMA_V1[2] == SQLITE_SCHEMA_V1[2].replace("INTO meta", "INTO {schema}.meta")


def test_postgres_schema_statements_are_single_statements_without_parameters() -> None:
    assert not any(";" in statement or "%" in statement for statement in POSTGRES_SCHEMA_V1)


def test_postgres_create_schema_composes_with_a_quoted_identifier() -> None:
    assert _compose(POSTGRES_CREATE_SCHEMA, "team_a") == 'CREATE SCHEMA IF NOT EXISTS "team_a"'
