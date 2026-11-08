"""Shared SQL layer of the SQLite and PostgreSQL adapters.

Schema DDL, migrations, the pure first-setup decision and the record <-> row codec. Imports
`environment_store.core` only.
"""

from environment_store.adapters.sql.codec import (
    Dialect,
    StoreInfoRow,
    StoreRow,
    record_to_row,
    row_to_info,
    row_to_record,
)
from environment_store.adapters.sql.migrations import (
    POSTGRES_MIGRATIONS,
    POSTGRES_SET_SCHEMA_VERSION,
    SQLITE_MIGRATIONS,
    SQLITE_SET_SCHEMA_VERSION,
    Migration,
    pending,
)
from environment_store.adapters.sql.schema import (
    META_APP,
    META_APP_KEY,
    META_TABLE,
    META_VERSION_KEY,
    POSTGRES_CREATE_SCHEMA,
    POSTGRES_SCHEMA_V1,
    SCHEMA_VERSION,
    SQLITE_SCHEMA_V1,
    STORE_INFO_COLUMNS,
    STORES_COLUMNS,
    STORES_TABLE,
)
from environment_store.adapters.sql.setup import (
    DatabaseInspection,
    SetupAction,
    SetupState,
    classify,
    decide,
    stored_version,
)

__all__ = [
    "META_APP",
    "META_APP_KEY",
    "META_TABLE",
    "META_VERSION_KEY",
    "POSTGRES_CREATE_SCHEMA",
    "POSTGRES_MIGRATIONS",
    "POSTGRES_SCHEMA_V1",
    "POSTGRES_SET_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SQLITE_MIGRATIONS",
    "SQLITE_SCHEMA_V1",
    "SQLITE_SET_SCHEMA_VERSION",
    "STORES_COLUMNS",
    "STORES_TABLE",
    "STORE_INFO_COLUMNS",
    "DatabaseInspection",
    "Dialect",
    "Migration",
    "SetupAction",
    "SetupState",
    "StoreInfoRow",
    "StoreRow",
    "classify",
    "decide",
    "pending",
    "record_to_row",
    "row_to_info",
    "row_to_record",
    "stored_version",
]
