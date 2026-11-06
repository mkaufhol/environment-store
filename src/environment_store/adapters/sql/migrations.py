"""Built-in schema migrations of the SQL adapters (D10, D11).

Migration 1 creates schema version 1 in an empty database; every later migration upgrades the
schema by one version. An adapter applies `pending(...)` migrations in one transaction: for each
migration, its statements and then the `*_SET_SCHEMA_VERSION` statement with the migration's
version as parameter, so `meta.schema_version` always matches the tables that exist.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from environment_store.adapters.sql.schema import POSTGRES_SCHEMA_V1, SQLITE_SCHEMA_V1
from environment_store.core.errors import SchemaTooNewError, ValidationError

__all__ = [
    "POSTGRES_MIGRATIONS",
    "POSTGRES_SET_SCHEMA_VERSION",
    "SQLITE_MIGRATIONS",
    "SQLITE_SET_SCHEMA_VERSION",
    "Migration",
    "pending",
]


def _check_version(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        message = f"{name} must be an integer >= 1, got {value!r}"
        raise ValidationError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class Migration:
    """The statements that bring the schema to `version`.

    Attributes:
        version: The schema version after this migration, starting at 1.
        statements: Constant SQL statements, executed in order; PostgreSQL statements use the
            `{schema}` placeholder.
    """

    version: int
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the migration and copy the statements into a tuple.

        Raises:
            ValidationError: The version is not an integer >= 1, or there are no statements or
                a statement is not a non-blank string.
        """
        _check_version(self.version, "migration version")
        statements = self.statements
        if isinstance(statements, str) or not isinstance(statements, Sequence):
            message = "migration statements must be a sequence of SQL strings"
            raise ValidationError(message)
        if not statements or not all(
            isinstance(statement, str) and statement.strip() for statement in statements
        ):
            message = "migration statements must be one or more non-blank SQL strings"
            raise ValidationError(message)
        object.__setattr__(self, "statements", tuple(statements))


SQLITE_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(version=1, statements=SQLITE_SCHEMA_V1),
)
"""Every SQLite migration, ordered by version."""

POSTGRES_MIGRATIONS: Final[tuple[Migration, ...]] = (
    Migration(version=1, statements=POSTGRES_SCHEMA_V1),
)
"""Every PostgreSQL migration, ordered by version; statements use `{schema}`."""

SQLITE_SET_SCHEMA_VERSION: Final = "UPDATE meta SET value = ? WHERE key = 'schema_version'"
"""Records the new version after a migration; one parameter, the version as text."""

POSTGRES_SET_SCHEMA_VERSION: Final = (
    "UPDATE {schema}.meta SET value = %s WHERE key = 'schema_version'"
)
"""Records the new version after a migration; one parameter, the version as text."""


def pending(migrations: Sequence[Migration], current: int | None) -> list[Migration]:
    """Select the migrations that bring a database from `current` to the latest version.

    Args:
        migrations: All migrations of a dialect, numbered 1 to n without gaps (any order).
        current: The schema version found, or `None` for an empty database.

    Returns:
        The migrations to apply, ordered by version; empty when the schema is current.

    Raises:
        ValidationError: `current` is not an integer >= 1, or the migrations are not numbered
            1 to n.
        SchemaTooNewError: `current` is newer than the last migration (D13).
    """
    ordered = sorted(migrations, key=lambda migration: migration.version)
    if not ordered or [migration.version for migration in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        message = "migrations must be numbered 1 to n (n >= 1) without gaps or duplicates"
        raise ValidationError(message)
    if current is None:
        return ordered
    _check_version(current, "current schema version")
    if current > len(ordered):
        message = (
            f"the database schema version {current} is newer than this client supports "
            f"({len(ordered)}); upgrade environment-store"
        )
        raise SchemaTooNewError(message)
    return ordered[current:]
