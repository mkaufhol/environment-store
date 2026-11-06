"""Inspecting and migrating the dedicated PostgreSQL schema (D11, D13).

The caller runs these inside one transaction that holds the schema's advisory lock, so that
inspection, decision and migration see one consistent state and racing first opens serialise.
Every statement is composed with `psycopg.sql`; the schema name is always an `Identifier`.
"""

from collections.abc import Sequence
from typing import Final, LiteralString, cast

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from environment_store.adapters.sql.migrations import POSTGRES_SET_SCHEMA_VERSION, Migration
from environment_store.adapters.sql.schema import META_TABLE, POSTGRES_CREATE_SCHEMA
from environment_store.adapters.sql.setup import DatabaseInspection

__all__ = ["apply_migrations", "compose", "inspect_schema", "lock_schema"]

type Connection = psycopg.Connection[TupleRow]

_LOCK_NAMESPACE: Final = "environment-store schema "

# Every object that makes a schema "not empty" (D13): tables and partitioned tables by name;
# every other object with a prefix, so that it can never be mistaken for the `meta` table. That
# is every catalog with a namespace column; pg_type without the row types of relations and the
# array types created alongside another type, since those come with an object listed here.
_INSPECT: Final = sql.SQL("""
WITH target AS (SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = %(schema)s)
SELECT CASE WHEN c.relkind IN ('r', 'p') THEN c.relname ELSE 'relation:' || c.relname END
FROM pg_catalog.pg_class c WHERE c.relnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'function:' || proname FROM pg_catalog.pg_proc
WHERE pronamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'type:' || t.typname FROM pg_catalog.pg_type t
WHERE t.typnamespace = (SELECT oid FROM target) AND t.typtype <> 'c'
  AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_type e WHERE e.typarray = t.oid)
UNION ALL
SELECT 'collation:' || collname FROM pg_catalog.pg_collation
WHERE collnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'operator:' || oprname FROM pg_catalog.pg_operator
WHERE oprnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'operator class:' || opcname FROM pg_catalog.pg_opclass
WHERE opcnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'operator family:' || opfname FROM pg_catalog.pg_opfamily
WHERE opfnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'conversion:' || conname FROM pg_catalog.pg_conversion
WHERE connamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'statistics:' || stxname FROM pg_catalog.pg_statistic_ext
WHERE stxnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'text search configuration:' || cfgname FROM pg_catalog.pg_ts_config
WHERE cfgnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'text search dictionary:' || dictname FROM pg_catalog.pg_ts_dict
WHERE dictnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'text search parser:' || prsname FROM pg_catalog.pg_ts_parser
WHERE prsnamespace = (SELECT oid FROM target)
UNION ALL
SELECT 'text search template:' || tmplname FROM pg_catalog.pg_ts_template
WHERE tmplnamespace = (SELECT oid FROM target)
""")
_SCHEMA_EXISTS: Final = sql.SQL(
    "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %(schema)s)"
)
_READ_META: Final = sql.SQL(
    "SELECT key::text, value::text FROM {schema}.meta WHERE key IS NOT NULL AND value IS NOT NULL"
)


def compose(statement: str, schema: str) -> sql.Composed:
    """Fill the `{schema}` placeholder of a constant statement with a quoted identifier.

    Args:
        statement: A constant SQL statement from `environment_store.adapters.sql`.
        schema: The (validated) schema name.

    Returns:
        The composed statement.
    """
    # The statements are module constants of adapters.sql, never user input; only the schema
    # name varies, and it goes in as an Identifier.
    template = sql.SQL(cast("LiteralString", statement))
    return template.format(schema=sql.Identifier(schema))


def lock_schema(connection: Connection, schema: str) -> None:
    """Take the transaction-scoped advisory lock that serialises setups of one schema.

    Args:
        connection: A connection inside a transaction.
        schema: The schema name.
    """
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_LOCK_NAMESPACE + schema,)
    )


def inspect_schema(connection: Connection, schema: str) -> tuple[DatabaseInspection, bool]:
    """Find out what the schema holds.

    Args:
        connection: A connection inside a transaction.
        schema: The schema name.

    Returns:
        The inspection for `classify`, and whether the schema exists at all.
    """
    parameters = {"schema": schema}
    exists = connection.execute(_SCHEMA_EXISTS, parameters).fetchone() == (True,)
    tables = frozenset(str(row[0]) for row in connection.execute(_INSPECT, parameters))
    meta = _read_meta(connection, schema) if META_TABLE in tables else None
    return DatabaseInspection(tables=tables, meta=meta), exists


def apply_migrations(
    connection: Connection,
    schema: str,
    migrations: Sequence[Migration],
    *,
    create_schema: bool,
) -> None:
    """Create the schema if asked and apply migrations, recording each version (D11).

    Args:
        connection: A connection inside the setup transaction.
        schema: The schema name.
        migrations: The pending migrations, ordered by version.
        create_schema: Whether the schema does not exist yet.
    """
    if create_schema:
        connection.execute(compose(POSTGRES_CREATE_SCHEMA, schema))
    for migration in migrations:
        for statement in migration.statements:
            connection.execute(compose(statement, schema))
        connection.execute(compose(POSTGRES_SET_SCHEMA_VERSION, schema), (str(migration.version),))


def _read_meta(connection: Connection, schema: str) -> dict[str, str]:
    try:
        # A savepoint, so that a foreign `meta` without these columns does not abort the
        # surrounding setup transaction.
        with connection.transaction():
            rows = connection.execute(_READ_META.format(schema=sql.Identifier(schema)))
            return {str(key): str(value) for key, value in rows}
    except psycopg.errors.UndefinedColumn:
        # Not our layout: an empty meta classifies the schema as foreign.
        return {}
