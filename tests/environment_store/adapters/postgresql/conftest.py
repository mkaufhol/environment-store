import os
from pathlib import Path

import pytest
import yoyo
from sqlalchemy import create_engine, text

from environment_store.adapters.postgresql import PostgreSQLAdapter

DATABASE_URL_ENV = "ENVIRONMENT_STORE_TEST_POSTGRES_URL"
MIGRATIONS_DIR = (
    Path(__file__).parents[4] / "src/environment_store/adapters/postgresql/migrations"
)


@pytest.fixture(scope="session")
def engine():
    """
    Engine for a throwaway PostgreSQL database (version 15+).

    Set ENVIRONMENT_STORE_TEST_POSTGRES_URL to e.g.
    ``postgresql+psycopg://postgres@localhost:5432/env_store_test``. The database's
    ``environment_store`` table is truncated between tests, so never point this at real data.
    """
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        pytest.skip(f"{DATABASE_URL_ENV} is not set")
    backend = yoyo.get_backend(url)
    migrations = yoyo.read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def adapter(engine):
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE environment_store RESTART IDENTITY"))
    return PostgreSQLAdapter(engine)
