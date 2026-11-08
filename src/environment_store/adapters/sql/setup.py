"""What a SQL adapter does with the database it finds on connect.

Pure: the adapter inspects the database (its tables and the `meta` rows), `classify` names the
state and `decide` turns it into an action or refuses. Refusing raises before anything is written,
so a foreign or too new database is never changed.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum, auto
from types import MappingProxyType
from typing import Final

from environment_store.adapters.sql.schema import (
    META_APP,
    META_APP_KEY,
    META_TABLE,
    META_VERSION_KEY,
    SCHEMA_VERSION,
)
from environment_store.core.errors import (
    DatabaseNotCleanError,
    SchemaOutdatedError,
    SchemaTooNewError,
    ValidationError,
)

__all__ = [
    "DatabaseInspection",
    "SetupAction",
    "SetupState",
    "classify",
    "decide",
    "stored_version",
]

# Plain ASCII digits without sign, padding or leading zero; the length cap keeps the value an
# ordinary integer. Anything else is not a version this tool wrote.
_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"[1-9][0-9]{0,17}")


@dataclass(frozen=True, slots=True, kw_only=True)
class DatabaseInspection:
    """What an adapter found in the database (SQLite file or PostgreSQL schema).

    Attributes:
        tables: Names of all tables (SQLite: in the file; PostgreSQL: in the dedicated schema).
        meta: The rows of the `meta` table as key -> value, or `None` if there is no `meta`
            table; read-only.
    """

    tables: frozenset[str]
    meta: Mapping[str, str] | None

    def __post_init__(self) -> None:
        """Copy the tables and meta rows and check that they are consistent.

        Raises:
            ValidationError: `tables` is not a collection of names, `meta` is not a mapping,
                or `meta` is given although there is no `meta` table.
        """
        object.__setattr__(self, "tables", _table_names(self.tables))
        if self.meta is None:
            return
        if not isinstance(self.meta, Mapping):
            message = "inspection meta must be a mapping or None"
            raise ValidationError(message)
        if META_TABLE not in self.tables:
            message = f"inspection meta given, but there is no {META_TABLE!r} table"
            raise ValidationError(message)
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))


class SetupState(StrEnum):
    """State of the database found on connect."""

    # auto() gives the lowercase member name.
    EMPTY = auto()
    """No tables: SQLite new file or no tables, PostgreSQL no or empty schema."""
    CURRENT = auto()
    """Ours, same schema version as this client."""
    OUTDATED = auto()
    """Ours, older schema version."""
    NEWER = auto()
    """Ours, newer schema version than this client."""
    FOREIGN = auto()
    """Tables without a valid `meta`, a `meta` of another app, or a non-integer version."""


class SetupAction(StrEnum):
    """What the adapter does with the database."""

    CREATE = auto()
    """Create schema version 1 (and upgrade to the latest version)."""
    USE = auto()
    """Use the schema as it is."""
    UPGRADE = auto()
    """Apply the pending migrations."""


def stored_version(inspection: DatabaseInspection) -> int | None:
    """Return the schema version of our schema.

    Args:
        inspection: What the adapter found.

    Returns:
        The version from `meta`, or `None` if the database has no valid `meta` of ours.
    """
    meta = inspection.meta
    if meta is None or meta.get(META_APP_KEY) != META_APP:
        return None
    version = meta.get(META_VERSION_KEY)
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        return None
    return int(version)


def classify(inspection: DatabaseInspection, *, client_version: int = SCHEMA_VERSION) -> SetupState:
    """Name the state of an inspected database.

    Args:
        inspection: What the adapter found.
        client_version: The schema version this client understands.

    Returns:
        The state.
    """
    if not inspection.tables:
        return SetupState.EMPTY
    version = stored_version(inspection)
    if version is None:
        return SetupState.FOREIGN
    if version < client_version:
        return SetupState.OUTDATED
    if version > client_version:
        return SetupState.NEWER
    return SetupState.CURRENT


def decide(state: SetupState, *, auto_upgrade: bool, location: str = "the database") -> SetupAction:
    """Decide what to do with a database, or refuse.

    Args:
        state: The state from `classify`.
        auto_upgrade: Whether an outdated schema is upgraded on connect (SQLite: yes,
            PostgreSQL: no, only via `migrate`).
        location: Where the database is, for error messages (a path or schema name, never
            credentials).

    Returns:
        The action to take.

    Raises:
        DatabaseNotCleanError: The database holds foreign content.
        SchemaTooNewError: The schema is newer than this client.
        SchemaOutdatedError: The schema is older and `auto_upgrade` is false.
    """
    if state is SetupState.EMPTY:
        return SetupAction.CREATE
    if state is SetupState.CURRENT:
        return SetupAction.USE
    if state is SetupState.OUTDATED and auto_upgrade:
        return SetupAction.UPGRADE
    if state is SetupState.OUTDATED:
        message = (
            f"the environment-store schema in {location} is outdated; "
            "run 'environment-store migrate' to upgrade it"
        )
        raise SchemaOutdatedError(message)
    if state is SetupState.NEWER:
        message = (
            f"the environment-store schema in {location} is newer than this client "
            "supports; upgrade environment-store"
        )
        raise SchemaTooNewError(message)
    # The only state left is FOREIGN.
    message = (
        f"{location} is not empty and is not an environment-store database (no valid "
        f"{META_TABLE!r} table); nothing was created or changed. Use an empty database "
        "(PostgreSQL: or another ?schema=)"
    )
    raise DatabaseNotCleanError(message)


def _table_names(tables: object) -> frozenset[str]:
    if isinstance(tables, str) or not isinstance(tables, Iterable):
        message = "inspection tables must be a collection of table names"
        raise ValidationError(message)
    names = frozenset(tables)
    if not all(isinstance(name, str) for name in names):
        message = "inspection tables must be a collection of table names (strings)"
        raise ValidationError(message)
    return names
