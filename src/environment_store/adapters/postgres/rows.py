"""The statements on the `stores` table and the conversions of its rows.

Statements are templates for `sql.SQL.format(schema=..., ...)`; values are always parameters.
The session is pinned to UTC; driver values are untrusted and validated by the shared codec.
"""

from datetime import UTC, datetime
from typing import Final

from psycopg import sql
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from environment_store.adapters.sql.codec import Dialect, StoreInfoRow, StoreRow, record_to_row
from environment_store.adapters.sql.schema import STORE_INFO_COLUMNS, STORES_COLUMNS
from environment_store.core.models import StoreRecord

__all__ = [
    "COLUMNS",
    "CREATE",
    "DELETE",
    "INFO_COLUMNS",
    "LIST",
    "PLACEHOLDERS",
    "READ",
    "REVISION",
    "WRITE",
    "info_row",
    "record_parameters",
    "store_row",
]

COLUMNS: Final = sql.SQL(", ").join(map(sql.Identifier, STORES_COLUMNS))
INFO_COLUMNS: Final = sql.SQL(", ").join(map(sql.Identifier, STORE_INFO_COLUMNS))
PLACEHOLDERS: Final = sql.SQL(", ").join(sql.Placeholder() for _ in STORES_COLUMNS)

# COLLATE "C" sorts UTF-8 by byte, which is code point order, whatever the database collation.
LIST: Final = sql.SQL('SELECT {columns} FROM {schema}.stores ORDER BY name COLLATE "C"')
READ: Final = sql.SQL("SELECT {columns} FROM {schema}.stores WHERE name = %s")
CREATE: Final = sql.SQL(
    "INSERT INTO {schema}.stores ({columns}) VALUES ({values}) ON CONFLICT (name) DO NOTHING"
)
# The revision check and the replacement are one statement, so the check is atomic.
WRITE: Final = sql.SQL(
    "UPDATE {schema}.stores SET encrypted = %s, cipher_meta = %s, variables = %s, "
    "ciphertext = %s, revision = %s, created_at = %s, updated_at = %s "
    "WHERE name = %s AND revision = %s"
)
REVISION: Final = sql.SQL("SELECT revision FROM {schema}.stores WHERE name = %s")
DELETE: Final = sql.SQL("DELETE FROM {schema}.stores WHERE name = %s")


def record_parameters(record: StoreRecord) -> tuple[object, ...]:
    """The `stores` column values of a record, in DDL order, ready for psycopg."""
    row = record_to_row(record, dialect=Dialect.POSTGRES)
    return (
        row.name,
        row.encrypted,
        None if row.cipher_meta is None else Jsonb(row.cipher_meta),
        None if row.variables is None else Jsonb(row.variables),
        row.ciphertext,
        row.revision,
        row.created_at,
        row.updated_at,
    )


def _utc(value: datetime) -> datetime:
    # The session is pinned to UTC (_PIN_UTC); this only normalises the driver's tzinfo. A stored
    # instant outside years 1 to 9999 UTC already fails while loading, as a BackendError.
    return value.astimezone(UTC)


def store_row(row: TupleRow) -> StoreRow:
    """The `stores` row of a `SELECT` of every column; the codec validates every value."""
    name, encrypted, cipher_meta, variables, ciphertext, revision, created, updated = row
    return StoreRow(
        name=name,
        encrypted=encrypted,
        cipher_meta=cipher_meta,
        variables=variables,
        ciphertext=ciphertext,
        revision=revision,
        created_at=_utc(created),
        updated_at=_utc(updated),
    )


def info_row(row: TupleRow) -> StoreInfoRow:
    """The listing row of a `SELECT` of the info columns; the codec validates every value."""
    name, encrypted, cipher_meta, revision, created, updated = row
    return StoreInfoRow(
        name=name,
        encrypted=encrypted,
        cipher_meta=cipher_meta,
        revision=revision,
        created_at=_utc(created),
        updated_at=_utc(updated),
    )
