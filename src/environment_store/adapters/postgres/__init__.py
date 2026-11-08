"""PostgreSQL adapter; needs the `postgres` extra (`psycopg` 3).

`psycopg` is imported when this package is imported, so that `open_adapter` turns a missing
driver into `MissingExtraError("postgres")`.
"""

from environment_store.adapters.postgres.adapter import PostgresAdapter, open_postgres

__all__ = ["PostgresAdapter", "open_postgres"]
