"""Conversion between `StoreRecord`s and rows of the `stores` table, per SQL dialect.

| Column | SQLite | PostgreSQL |
|---|---|---|
| `encrypted` | `int` 0/1 | `bool` |
| `variables`, `cipher_meta` | canonical JSON `str` | `dict` (the adapter wraps it in `Jsonb`) |
| `ciphertext` | `bytes` | `bytes` |
| timestamps | ISO 8601 UTC `str` with microseconds | aware `datetime` |

Rows read from a database are untrusted: decoding validates every column, and a corrupt row
raises `BackendError` naming the store but never a value.
"""

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Final

from environment_store.adapters.sql.schema import STORES_COLUMNS
from environment_store.core.errors import BackendError, UnsupportedFormatError, ValidationError
from environment_store.core.models import CipherMeta, KeyMode, StoreInfo, StoreRecord

__all__ = [
    "Dialect",
    "StoreInfoRow",
    "StoreRow",
    "record_to_row",
    "row_to_info",
    "row_to_record",
]

type JsonColumn = str | Mapping[str, object] | None
"""A JSON column: text on SQLite, a parsed object on PostgreSQL."""
type Timestamp = str | datetime
"""A timestamp column: ISO 8601 text on SQLite, an aware `datetime` on PostgreSQL."""

_UTC_SUFFIX: Final = "+00:00"


class Dialect(StrEnum):
    """The SQL dialect a row is encoded for."""

    # auto() gives the lowercase member name: "sqlite", "postgres".
    SQLITE = auto()
    POSTGRES = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreRow:
    """One row of the `stores` table; the fields are the columns in DDL order.

    JSON objects are deep-copied on construction, so a row never shares state with its caller.
    `variables` and `ciphertext` stay out of the `repr`: values may be secrets.
    """

    name: str
    encrypted: bool | int
    cipher_meta: JsonColumn
    variables: JsonColumn = field(repr=False)
    ciphertext: bytes | bytearray | memoryview | None = field(repr=False)
    revision: int
    created_at: Timestamp
    updated_at: Timestamp

    def __post_init__(self) -> None:
        """Copy JSON objects so the row does not share them."""
        for column in ("cipher_meta", "variables"):
            value = getattr(self, column)
            if isinstance(value, Mapping):
                object.__setattr__(self, column, copy.deepcopy(dict(value)))

    def values(self) -> tuple[object, ...]:
        """Return the column values in DDL order, e.g. as `INSERT` parameters.

        Returns:
            One value per column of `stores`.
        """
        return tuple(getattr(self, column) for column in STORES_COLUMNS)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreInfoRow:
    """The columns of a `stores` row that a listing needs: everything except the payloads."""

    name: str
    encrypted: bool | int
    cipher_meta: JsonColumn
    revision: int
    created_at: Timestamp
    updated_at: Timestamp

    def __post_init__(self) -> None:
        """Copy a JSON object so the row does not share it."""
        if isinstance(self.cipher_meta, Mapping):
            object.__setattr__(self, "cipher_meta", copy.deepcopy(dict(self.cipher_meta)))


def record_to_row(record: StoreRecord, *, dialect: Dialect) -> StoreRow:
    """Encode a record as a `stores` row.

    Args:
        record: The (valid) record.
        dialect: The target dialect.

    Returns:
        The row, with column values in the dialect's representation.
    """
    meta = None if record.cipher_meta is None else record.cipher_meta.to_json()
    variables = None if record.variables is None else dict(record.variables)
    if dialect is Dialect.SQLITE:
        return StoreRow(
            name=record.name,
            encrypted=int(record.encrypted),
            cipher_meta=None if meta is None else _json_text(meta),
            variables=None if variables is None else _json_text(variables),
            ciphertext=record.ciphertext,
            revision=record.revision,
            created_at=_timestamp_text(record.created_at),
            updated_at=_timestamp_text(record.updated_at),
        )
    return StoreRow(
        name=record.name,
        encrypted=record.encrypted,
        cipher_meta=meta,
        variables=variables,
        ciphertext=record.ciphertext,
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def row_to_record(row: StoreRow, *, dialect: Dialect) -> StoreRecord:
    """Decode and validate a `stores` row.

    Args:
        row: The row as the driver returned it; untrusted.
        dialect: The dialect the row comes from.

    Returns:
        The record.

    Raises:
        UnsupportedFormatError: The cipher metadata is not recognised.
        BackendError: Any other corrupt column.
    """
    encrypted = _decode_flag(row.encrypted, store=row.name, dialect=dialect)
    cipher_meta = _decode_json(
        row.cipher_meta, store=row.name, column="cipher_meta", dialect=dialect
    )
    variables = _decode_json(row.variables, store=row.name, column="variables", dialect=dialect)
    try:
        meta = None if cipher_meta is None else CipherMeta.from_json(cipher_meta)
    except UnsupportedFormatError as err:
        message = f"store {row.name!r}: {err}"
        raise UnsupportedFormatError(message) from err
    ciphertext = row.ciphertext
    if isinstance(ciphertext, bytearray | memoryview):
        ciphertext = bytes(ciphertext)
    try:
        record = StoreRecord(
            name=row.name,
            revision=row.revision,
            created_at=_decode_timestamp(row.created_at, store=row.name, dialect=dialect),
            updated_at=_decode_timestamp(row.updated_at, store=row.name, dialect=dialect),
            variables=variables,  # ty: ignore[invalid-argument-type] - validated by StoreRecord
            ciphertext=ciphertext,
            cipher_meta=meta,
        )
    except ValidationError as err:
        raise _corrupt(row.name, str(err)) from err
    if record.encrypted != encrypted:
        raise _corrupt(row.name, "the encrypted flag does not match the stored payload")
    return record


def row_to_info(row: StoreInfoRow, *, dialect: Dialect) -> StoreInfo:
    """Decode a listing row; never fails on unrecognised cipher metadata.

    Args:
        row: The row as the driver returned it; untrusted.
        dialect: The dialect the row comes from.

    Returns:
        The listing entry; `key_mode` is `None` for plaintext stores and for cipher metadata
        this version does not recognise.

    Raises:
        BackendError: A corrupt name, flag, revision or timestamp.
    """
    encrypted = _decode_flag(row.encrypted, store=row.name, dialect=dialect)
    try:
        return StoreInfo(
            name=row.name,
            encrypted=encrypted,
            key_mode=_key_mode(row.cipher_meta, dialect=dialect) if encrypted else None,
            revision=row.revision,
            created_at=_decode_timestamp(row.created_at, store=row.name, dialect=dialect),
            updated_at=_decode_timestamp(row.updated_at, store=row.name, dialect=dialect),
        )
    except ValidationError as err:
        raise _corrupt(row.name, str(err)) from err


# --- encoding ----------------------------------------------------------------------------------


def _json_text(document: Mapping[str, object]) -> str:
    # Canonical form: stable text for equal documents, readable non-ASCII.
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _timestamp_text(value: datetime) -> str:
    # Fixed width with microseconds, so text order is time order.
    text = value.astimezone(UTC).isoformat(timespec="microseconds")
    return text.removesuffix(_UTC_SUFFIX) + "Z"


# --- decoding ----------------------------------------------------------------------------------


def _corrupt(store: object, detail: str) -> BackendError:
    return BackendError(f"store {store!r}: corrupt row in the database: {detail}")


def _decode_flag(value: object, *, store: object, dialect: Dialect) -> bool:
    if dialect is Dialect.SQLITE:
        # bool is an int subclass and acceptable; 2 or "1" are not.
        if isinstance(value, int) and value in {0, 1}:
            return bool(value)
    elif isinstance(value, bool):
        return value
    raise _corrupt(store, "the encrypted flag is not a boolean")


def _decode_json(value: object, *, store: object, column: str, dialect: Dialect) -> object:
    if value is None or dialect is Dialect.POSTGRES:
        # psycopg parses JSONB itself; the models validate the shape.
        return value
    if not isinstance(value, str):
        raise _corrupt(store, f"{column} is not JSON text")
    try:
        return json.loads(value)
    except (ValueError, RecursionError) as err:
        # RecursionError: nesting too deep for the decoder, still a corrupt document.
        # The decoder's message is not used: it may quote the (secret) document.
        raise _corrupt(store, f"{column} is not valid JSON") from err


def _decode_timestamp(value: object, *, store: object, dialect: Dialect) -> datetime:
    if dialect is Dialect.POSTGRES:
        if isinstance(value, datetime):
            return value
        raise _corrupt(store, "a timestamp is not a datetime")
    if not isinstance(value, str):
        raise _corrupt(store, "a timestamp is not ISO 8601 text")
    try:
        return datetime.fromisoformat(value)
    except ValueError as err:
        raise _corrupt(store, "a timestamp is not ISO 8601 text") from err


def _key_mode(cipher_meta: object, *, dialect: Dialect) -> KeyMode | None:
    document = cipher_meta
    if dialect is Dialect.SQLITE:
        if not isinstance(cipher_meta, str):
            return None
        try:
            document = json.loads(cipher_meta)
        except (ValueError, RecursionError):
            return None
    try:
        return CipherMeta.from_json(document).mode
    except UnsupportedFormatError:
        return None
