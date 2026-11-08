"""SQL schema version 1 for SQLite and PostgreSQL.

Both dialects share one layout: a key-value `meta` table that marks the database as ours and
holds the schema version, and one `stores` row per store. The statements are constants and
contain no user input. The PostgreSQL statements carry a `{schema}` placeholder for the dedicated
schema, which the PostgreSQL adapter fills with `psycopg.sql.Identifier`, never as text.
"""

from typing import Final

__all__ = [
    "META_APP",
    "META_APP_KEY",
    "META_TABLE",
    "META_VERSION_KEY",
    "POSTGRES_CREATE_SCHEMA",
    "POSTGRES_SCHEMA_V1",
    "SCHEMA_VERSION",
    "SQLITE_SCHEMA_V1",
    "STORES_COLUMNS",
    "STORES_TABLE",
    "STORE_INFO_COLUMNS",
]

SCHEMA_VERSION: Final[int] = 1
"""The schema version this client creates and understands."""

META_TABLE: Final = "meta"
META_APP_KEY: Final = "app"
META_VERSION_KEY: Final = "schema_version"
META_APP: Final = "environment-store"
"""Value of `meta.app` by which the tool recognises its own database."""

STORES_TABLE: Final = "stores"
STORES_COLUMNS: Final[tuple[str, ...]] = (
    "name",
    "encrypted",
    "cipher_meta",
    "variables",
    "ciphertext",
    "revision",
    "created_at",
    "updated_at",
)
"""The columns of `stores` in DDL order."""

STORE_INFO_COLUMNS: Final[tuple[str, ...]] = (
    "name",
    "encrypted",
    "cipher_meta",
    "revision",
    "created_at",
    "updated_at",
)
"""The columns a store listing needs: every column except the payloads."""

# Every statement is a literal (not formatted from the constants above); the tests check that the
# meta rows match META_APP and SCHEMA_VERSION.
SQLITE_SCHEMA_V1: Final[tuple[str, ...]] = (
    """CREATE TABLE meta (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
)""",
    # SQLite: JSONB -> TEXT (JSON), BYTEA -> BLOB, TIMESTAMPTZ -> TEXT (ISO 8601, UTC). SQLite
    # allows NULL in a non-integer primary key and has no boolean type, hence the extra NOT NULL
    # and the 0/1 check.
    """CREATE TABLE stores (
    name        TEXT NOT NULL PRIMARY KEY,
    encrypted   BOOLEAN NOT NULL CHECK (encrypted IN (0, 1)),
    cipher_meta TEXT,
    variables   TEXT,
    ciphertext  BLOB,
    revision    INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK (
        (encrypted AND cipher_meta IS NOT NULL AND ciphertext IS NOT NULL AND variables IS NULL)
        OR
        (NOT encrypted AND cipher_meta IS NULL AND variables IS NOT NULL AND ciphertext IS NULL)
    )
)""",
    "INSERT INTO meta (key, value) VALUES ('app', 'environment-store'), ('schema_version', '1')",
)
"""Statements that create schema version 1 in an empty SQLite database, in order."""

POSTGRES_SCHEMA_V1: Final[tuple[str, ...]] = (
    """CREATE TABLE {schema}.meta (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
)""",
    """CREATE TABLE {schema}.stores (
    name        TEXT NOT NULL PRIMARY KEY,
    encrypted   BOOLEAN NOT NULL,
    cipher_meta JSONB,
    variables   JSONB,
    ciphertext  BYTEA,
    revision    INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    CHECK (
        (encrypted AND cipher_meta IS NOT NULL AND ciphertext IS NOT NULL AND variables IS NULL)
        OR
        (NOT encrypted AND cipher_meta IS NULL AND variables IS NOT NULL AND ciphertext IS NULL)
    )
)""",
    "INSERT INTO {schema}.meta (key, value) "
    "VALUES ('app', 'environment-store'), ('schema_version', '1')",
)
"""Statements that create schema version 1 inside the (existing) `{schema}`, in order."""

POSTGRES_CREATE_SCHEMA: Final = "CREATE SCHEMA IF NOT EXISTS {schema}"
"""Creates the dedicated schema before `POSTGRES_SCHEMA_V1`, in the same transaction."""
