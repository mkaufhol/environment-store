"""PostgreSQL adapter (spec §3.3, D10-D13); needs the `postgres` extra (`psycopg` 3).

`psycopg` is imported when this package is imported, so that `open_adapter` turns a missing
driver into `MissingExtraError("postgres")` (IMPLEMENTATION-PLAN.md §4, B4).
"""

from environment_store.adapters.postgres.adapter import PostgresAdapter, open_postgres

__all__ = ["PostgresAdapter", "open_postgres"]
