# PostgreSQL (`PostgreSQLAdapter`)

Stores the variables in one table of a PostgreSQL database (version 15+). Install the `postgres` extra.

## Setting up the schema

The schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/) migrations, which you have to apply
before using the adapter. Copy `src/environment_store/adapters/postgresql/yoyo-database-example.ini` to
`yoyo-database.ini` in the same directory, point it to your database and run:

```bash
src/environment_store/adapters/postgresql/scripts/init_database.sh
```

## Usage

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.postgresql import PostgreSQLAdapter

# Either a SQLAlchemy engine or a database URL
adapter = PostgreSQLAdapter(
    "postgresql+psycopg://user:password@localhost:5432/environment_store"
)
manager = EnvironmentStoreManager(adapter=adapter)
```

## CLI / TUI

```bash
environment-store --backend postgres --database-url postgresql+psycopg://user:pass@localhost/envstore tui
```

| Option | Environment variable |
|--------|----------------------|
| `--database-url URL` | `ENVIRONMENT_STORE_DATABASE_URL` |

## Tests

The PostgreSQL tests are skipped unless `ENVIRONMENT_STORE_TEST_POSTGRES_URL` points to a throwaway database
(its `environment_store` table is truncated).

[Back to the overview](README.md)
