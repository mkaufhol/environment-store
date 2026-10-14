# PostgreSQL

Stores each variable as one row of the table `environment_store` (PostgreSQL 15 or newer). Needs the `postgres`
extra.

```python
from environment_store.adapters.postgresql import PostgreSQLAdapter

# a SQLAlchemy URL ...
adapter = PostgreSQLAdapter(
    "postgresql+psycopg://user:password@localhost:5432/environment_store"
)
# ... or an existing SQLAlchemy engine
adapter = PostgreSQLAdapter(engine)
```

```bash
export ENVIRONMENT_STORE_BACKEND=postgres
export ENVIRONMENT_STORE_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/environment_store
environment-store list
```

## Create the schema first

The database must exist, and the schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/) migrations
shipped inside the package. Apply them once, and again after upgrading the library:

```bash
environment-store migrate --status     # list pending migrations, change nothing
environment-store migrate              # apply them (safe to re-run)
```

or from Python:

```python
from environment_store.adapters.postgresql import apply_migrations, pending_migrations

pending_migrations(url)  # -> ["20260315_01_Dj4Bk-initial", ...]
apply_migrations(url)  # -> list of applied migration ids
```

Until the migrations are applied, commands fail with an error about the missing `environment_store` table.
If you work on a clone of the repository you can also use the yoyo CLI directly, see
[Development](../development.md#database-migrations).

## Notes

- One row per variable: `organization`, `project`, `environment`, `service`, `var`, `var_value` plus timestamps.
  `NULL` levels mean the variable lives higher up; a unique constraint (`NULLS NOT DISTINCT`) keeps names unique
  per level, and a check constraint enforces the no-skipping rule.
- `created_at` / `updated_at` are maintained by the database.
- Values are stored in plain text columns. Use database-level encryption and access control for secrets.

[Back to the storage backends overview](README.md)
