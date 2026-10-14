from pathlib import Path

import yoyo

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def pending_migrations(database_url: str) -> list[str]:
    """Return the ids of the migrations that have not been applied to the database yet."""
    backend = yoyo.get_backend(database_url)
    try:
        migrations = yoyo.read_migrations(str(MIGRATIONS_DIR))
        return [m.id for m in backend.to_apply(migrations)]
    finally:
        backend.connection.close()


def apply_migrations(database_url: str) -> list[str]:
    """Apply all pending migrations and return the ids of the applied ones."""
    backend = yoyo.get_backend(database_url)
    try:
        migrations = yoyo.read_migrations(str(MIGRATIONS_DIR))
        with backend.lock():
            to_apply = backend.to_apply(migrations)
            backend.apply_migrations(to_apply)
        return [m.id for m in to_apply]
    finally:
        backend.connection.close()
