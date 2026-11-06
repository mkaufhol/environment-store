import base64
import dataclasses
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.adapters.sql.codec import (
    Dialect,
    StoreInfoRow,
    StoreRow,
    record_to_row,
    row_to_info,
    row_to_record,
)
from environment_store.adapters.sql.schema import (
    SQLITE_SCHEMA_V1,
    STORE_INFO_COLUMNS,
    STORES_COLUMNS,
)
from environment_store.core.errors import BackendError, UnsupportedFormatError
from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode, StoreRecord
from tests.support.strategies import plain_records, sealed_records

_SALT = bytes(range(16))
_T0 = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 11, 6, 12, 30, 0, 123456, tzinfo=UTC)
_T0_TEXT = "2026-11-06T10:00:00.000000Z"
_T1_TEXT = "2026-11-06T12:30:00.123456Z"
_KEYFILE = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE)
_PASSPHRASE = CipherMeta(
    cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE, kdf=KdfParams(salt=_SALT)
)
_PLAIN = StoreRecord.plain(
    name="base",
    variables={"DB_HOST": "localhost", "A": "ä\n'x'"},
    created_at=_T0,
    updated_at=_T1,
    revision=3,
)
_SEALED = StoreRecord.sealed(
    name="vault",
    ciphertext=b"\x00nonce\xffdata",
    cipher_meta=_PASSPHRASE,
    created_at=_T0,
    updated_at=_T1,
    revision=7,
)
_FUTURE_META = {"cipher": "age", "mode": "x25519"}
# Nesting deep enough that json.loads raises RecursionError rather than ValueError.
_DEEP_JSON = "[" * 200_000 + "]" * 200_000


@pytest.fixture
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in SQLITE_SCHEMA_V1:
            connection.execute(statement)
        yield connection
    finally:
        connection.close()


def _sqlite_round_trip(connection: sqlite3.Connection, record: StoreRecord) -> StoreRecord:
    placeholders = ", ".join("?" for _ in STORES_COLUMNS)
    connection.execute(
        f"INSERT INTO stores VALUES ({placeholders})",  # noqa: S608 - fixed placeholders
        record_to_row(record, dialect=Dialect.SQLITE).values(),
    )
    values = connection.execute("SELECT * FROM stores WHERE name = ?", (record.name,)).fetchone()
    connection.execute("DELETE FROM stores")
    return row_to_record(
        StoreRow(**dict(zip(STORES_COLUMNS, values, strict=True))), dialect=Dialect.SQLITE
    )


def _sqlite_row(**overrides: object) -> StoreRow:
    return dataclasses.replace(record_to_row(_PLAIN, dialect=Dialect.SQLITE), **overrides)


def _sqlite_sealed_row(**overrides: object) -> StoreRow:
    return dataclasses.replace(record_to_row(_SEALED, dialect=Dialect.SQLITE), **overrides)


def _postgres_row(**overrides: object) -> StoreRow:
    return dataclasses.replace(record_to_row(_PLAIN, dialect=Dialect.POSTGRES), **overrides)


def _info_row(record: StoreRecord, dialect: Dialect, **overrides: object) -> StoreInfoRow:
    row = record_to_row(record, dialect=dialect)
    values = {column: getattr(row, column) for column in STORE_INFO_COLUMNS}
    values.update(overrides)
    return StoreInfoRow(**values)


# --- types -------------------------------------------------------------------------------------


def test_dialects_are_sqlite_and_postgres() -> None:
    assert [dialect.value for dialect in Dialect] == ["sqlite", "postgres"]


def test_store_row_fields_are_the_stores_columns_in_ddl_order() -> None:
    assert tuple(field.name for field in dataclasses.fields(StoreRow)) == STORES_COLUMNS


def test_store_info_row_fields_are_the_listing_columns() -> None:
    assert tuple(field.name for field in dataclasses.fields(StoreInfoRow)) == STORE_INFO_COLUMNS


def test_store_row_values_are_in_column_order() -> None:
    row = record_to_row(_SEALED, dialect=Dialect.SQLITE)

    assert row.values() == tuple(getattr(row, column) for column in STORES_COLUMNS)


def test_store_row_values_keep_a_driver_buffer_as_it_is() -> None:
    buffer = memoryview(b"\x00nonce")
    row = _sqlite_sealed_row(ciphertext=buffer)

    assert row.values()[4] is buffer


def test_store_row_repr_hides_variables_and_ciphertext() -> None:
    plain = repr(record_to_row(_PLAIN, dialect=Dialect.POSTGRES))
    sealed = repr(record_to_row(_SEALED, dialect=Dialect.SQLITE))

    assert "localhost" not in plain
    assert "nonce" not in sealed


def test_store_row_copies_json_mappings_on_construction() -> None:
    variables = {"A": "1"}
    meta: dict[str, object] = {"cipher": "aes256gcm", "mode": "passphrase", "kdf": {"t": 3}}

    row = StoreRow(
        name="base",
        encrypted=False,
        cipher_meta=meta,
        variables=variables,
        ciphertext=None,
        revision=1,
        created_at=_T0,
        updated_at=_T0,
    )
    variables["A"] = "changed"
    meta["kdf"]["t"] = 4

    assert row.variables == {"A": "1"}
    assert row.cipher_meta == {"cipher": "aes256gcm", "mode": "passphrase", "kdf": {"t": 3}}


def test_store_row_is_frozen() -> None:
    row = record_to_row(_PLAIN, dialect=Dialect.SQLITE)

    with pytest.raises(dataclasses.FrozenInstanceError):
        row.revision = 4  # ty: ignore[invalid-assignment] - frozen on purpose


# --- record_to_row: SQLite ---------------------------------------------------------------------


def test_sqlite_plaintext_row_holds_canonical_json_and_iso_timestamps() -> None:
    row = record_to_row(_PLAIN, dialect=Dialect.SQLITE)

    assert row == StoreRow(
        name="base",
        encrypted=0,
        cipher_meta=None,
        variables='{"A":"ä\\n\'x\'","DB_HOST":"localhost"}',
        ciphertext=None,
        revision=3,
        created_at=_T0_TEXT,
        updated_at=_T1_TEXT,
    )


def test_sqlite_encrypted_row_holds_cipher_meta_json_and_ciphertext_bytes() -> None:
    row = record_to_row(_SEALED, dialect=Dialect.SQLITE)

    salt = base64.b64encode(_SALT).decode("ascii")
    assert row == StoreRow(
        name="vault",
        encrypted=1,
        cipher_meta=(
            '{"cipher":"aes256gcm","kdf":{"m":65536,"name":"argon2id","p":4,'
            f'"salt":"{salt}","t":3}},"mode":"passphrase"}}'
        ),
        variables=None,
        ciphertext=b"\x00nonce\xffdata",
        revision=7,
        created_at=_T0_TEXT,
        updated_at=_T1_TEXT,
    )


def test_sqlite_encrypted_flag_is_an_int() -> None:
    assert type(record_to_row(_PLAIN, dialect=Dialect.SQLITE).encrypted) is int
    assert type(record_to_row(_SEALED, dialect=Dialect.SQLITE).encrypted) is int


def test_sqlite_timestamps_are_utc_with_microseconds() -> None:
    record = StoreRecord.plain(
        name="base",
        variables={},
        created_at=datetime(2026, 11, 6, 11, 0, tzinfo=timezone(timedelta(hours=1))),
    )

    row = record_to_row(record, dialect=Dialect.SQLITE)

    assert (row.created_at, row.updated_at) == (_T0_TEXT, _T0_TEXT)


# --- record_to_row: PostgreSQL -----------------------------------------------------------------


def test_postgres_plaintext_row_holds_a_dict_and_aware_datetimes() -> None:
    row = record_to_row(_PLAIN, dialect=Dialect.POSTGRES)

    assert row == StoreRow(
        name="base",
        encrypted=False,
        cipher_meta=None,
        variables={"DB_HOST": "localhost", "A": "ä\n'x'"},
        ciphertext=None,
        revision=3,
        created_at=_T0,
        updated_at=_T1,
    )
    assert type(row.variables) is dict


def test_postgres_encrypted_row_holds_cipher_meta_dict() -> None:
    row = record_to_row(_SEALED, dialect=Dialect.POSTGRES)

    assert row.encrypted is True
    assert row.cipher_meta == _PASSPHRASE.to_json()
    assert (row.variables, row.ciphertext) == (None, b"\x00nonce\xffdata")


def test_postgres_row_json_is_serialisable() -> None:
    row = record_to_row(_SEALED, dialect=Dialect.POSTGRES)

    assert json.loads(json.dumps(row.cipher_meta)) == row.cipher_meta


# --- row_to_record -----------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", list(Dialect))
@pytest.mark.parametrize("record", [_PLAIN, _SEALED], ids=["plain", "sealed"])
def test_row_to_record_inverts_record_to_row(dialect: Dialect, record: StoreRecord) -> None:
    assert row_to_record(record_to_row(record, dialect=dialect), dialect=dialect) == record


@pytest.mark.parametrize("dialect", list(Dialect))
@given(record=st.one_of(plain_records(), sealed_records()))
def test_every_record_round_trips_through_a_row(dialect: Dialect, record: StoreRecord) -> None:
    assert row_to_record(record_to_row(record, dialect=dialect), dialect=dialect) == record


@given(record=st.one_of(plain_records(), sealed_records()))
def test_every_record_round_trips_through_a_sqlite_database(record: StoreRecord) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in SQLITE_SCHEMA_V1:
            connection.execute(statement)

        assert _sqlite_round_trip(connection, record) == record
    finally:
        connection.close()


def test_sqlite_database_round_trip_keeps_keyfile_records(database: sqlite3.Connection) -> None:
    record = dataclasses.replace(_SEALED, cipher_meta=_KEYFILE)

    assert _sqlite_round_trip(database, record) == record


@pytest.mark.parametrize("buffer", [bytearray, memoryview])
def test_row_to_record_accepts_driver_buffers_as_ciphertext(buffer: type) -> None:
    row = _sqlite_sealed_row(ciphertext=buffer(b"\x00nonce\xffdata"))

    assert row_to_record(row, dialect=Dialect.SQLITE) == _SEALED


def test_row_to_record_accepts_a_bool_flag_from_sqlite() -> None:
    assert row_to_record(_sqlite_row(encrypted=False), dialect=Dialect.SQLITE) == _PLAIN


def test_row_to_record_reads_offset_timestamps_from_sqlite_as_utc() -> None:
    row = _sqlite_row(created_at="2026-11-06T11:00:00+01:00")

    assert row_to_record(row, dialect=Dialect.SQLITE).created_at == _T0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"name": "Bad/Name"}, id="invalid-name"),
        pytest.param({"revision": 0}, id="revision-0"),
        pytest.param({"revision": "3"}, id="revision-text"),
        pytest.param({"encrypted": 2}, id="flag-2"),
        pytest.param({"encrypted": "0"}, id="flag-text"),
        pytest.param({"encrypted": None}, id="flag-null"),
        pytest.param({"encrypted": 1}, id="flag-encrypted-but-plaintext"),
        pytest.param({"variables": "{not json"}, id="variables-not-json"),
        pytest.param({"variables": _DEEP_JSON}, id="variables-too-deep"),
        pytest.param({"variables": b"{}"}, id="variables-bytes"),
        pytest.param({"variables": "[]"}, id="variables-not-object"),
        pytest.param({"variables": '{"A": 1}'}, id="value-not-string"),
        pytest.param({"variables": '{"bad-name": "x"}'}, id="invalid-variable-name"),
        pytest.param({"variables": None}, id="no-payload"),
        pytest.param({"ciphertext": b"x"}, id="both-payloads"),
        pytest.param({"created_at": "yesterday"}, id="timestamp-not-iso"),
        pytest.param({"created_at": "2026-11-06T10:00:00"}, id="timestamp-naive"),
        pytest.param({"created_at": _T0}, id="timestamp-datetime"),
        pytest.param({"updated_at": "2026-11-06T09:00:00Z"}, id="updated-before-created"),
    ],
)
def test_corrupt_sqlite_rows_raise_backend_error_naming_the_store(
    overrides: dict[str, object],
) -> None:
    row = _sqlite_row(**overrides)

    with pytest.raises(BackendError, match="store '"):
        row_to_record(row, dialect=Dialect.SQLITE)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"encrypted": 1}, id="flag-1"),
        pytest.param({"encrypted": None}, id="flag-null"),
        pytest.param({"encrypted": True}, id="flag-encrypted-but-plaintext"),
        pytest.param({"variables": '{"A": "1"}'}, id="variables-as-text"),
        pytest.param({"variables": ["A"]}, id="variables-not-object"),
        pytest.param({"created_at": _T0_TEXT}, id="timestamp-text"),
        pytest.param({"created_at": datetime(2026, 11, 6)}, id="timestamp-naive"),  # noqa: DTZ001 - naive on purpose
    ],
)
def test_corrupt_postgres_rows_raise_backend_error_naming_the_store(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(BackendError, match="store 'base'"):
        row_to_record(_postgres_row(**overrides), dialect=Dialect.POSTGRES)


@pytest.mark.parametrize(
    "cipher_meta",
    [
        pytest.param('{"cipher":"age","mode":"keyfile"}', id="unknown-cipher"),
        pytest.param('{"cipher":"aes256gcm","mode":"hsm"}', id="unknown-mode"),
        pytest.param("[]", id="not-an-object"),
    ],
)
def test_unrecognised_cipher_meta_raises_unsupported_format_naming_the_store(
    cipher_meta: str,
) -> None:
    with pytest.raises(UnsupportedFormatError, match="store 'vault'"):
        row_to_record(_sqlite_sealed_row(cipher_meta=cipher_meta), dialect=Dialect.SQLITE)


def test_sealed_sqlite_row_with_too_deep_cipher_meta_raises_backend_error() -> None:
    with pytest.raises(BackendError, match=r"store 'vault'.*cipher_meta is not valid JSON"):
        row_to_record(_sqlite_sealed_row(cipher_meta=_DEEP_JSON), dialect=Dialect.SQLITE)


def test_sealed_row_with_text_ciphertext_raises_backend_error() -> None:
    with pytest.raises(BackendError, match="store 'vault'"):
        row_to_record(_sqlite_sealed_row(ciphertext="nonce"), dialect=Dialect.SQLITE)


def test_corrupt_row_errors_never_echo_values() -> None:
    rows = [
        _sqlite_row(variables='{"A": "s3cret", "bad-name": "s3cret"}'),
        _sqlite_row(variables='{"A": "s3cret" "B": 1}'),
        _sqlite_row(variables='{"A": "s3cret\\u0000"}'),
    ]

    for row in rows:
        with pytest.raises(BackendError) as caught:
            row_to_record(row, dialect=Dialect.SQLITE)
        assert "s3cret" not in str(caught.value)


# --- row_to_info -------------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", list(Dialect))
@pytest.mark.parametrize(
    "record",
    [_PLAIN, _SEALED, dataclasses.replace(_SEALED, cipher_meta=_KEYFILE)],
    ids=["plain", "passphrase", "keyfile"],
)
def test_row_to_info_matches_the_record_info(dialect: Dialect, record: StoreRecord) -> None:
    assert row_to_info(_info_row(record, dialect), dialect=dialect) == record.info


@pytest.mark.parametrize(
    ("dialect", "cipher_meta"),
    [
        pytest.param(Dialect.SQLITE, json.dumps(_FUTURE_META), id="sqlite-unknown-cipher"),
        pytest.param(Dialect.SQLITE, "{not json", id="sqlite-not-json"),
        pytest.param(Dialect.SQLITE, _DEEP_JSON, id="sqlite-too-deep"),
        pytest.param(Dialect.SQLITE, 42, id="sqlite-not-text"),
        pytest.param(Dialect.SQLITE, None, id="sqlite-missing"),
        pytest.param(Dialect.POSTGRES, _FUTURE_META, id="postgres-unknown-cipher"),
        pytest.param(Dialect.POSTGRES, "{}", id="postgres-not-object"),
    ],
)
def test_row_to_info_never_fails_on_unrecognised_cipher_meta(
    dialect: Dialect, cipher_meta: object
) -> None:
    info = row_to_info(_info_row(_SEALED, dialect, cipher_meta=cipher_meta), dialect=dialect)

    assert (info.name, info.encrypted, info.key_mode) == ("vault", True, None)
    assert (info.revision, info.created_at, info.updated_at) == (7, _T0, _T1)


@pytest.mark.parametrize(
    ("dialect", "overrides"),
    [
        pytest.param(Dialect.SQLITE, {"name": "../x"}, id="sqlite-invalid-name"),
        pytest.param(Dialect.SQLITE, {"encrypted": 5}, id="sqlite-flag-5"),
        pytest.param(Dialect.SQLITE, {"revision": -1}, id="sqlite-revision"),
        pytest.param(Dialect.SQLITE, {"created_at": "nope"}, id="sqlite-timestamp"),
        pytest.param(Dialect.POSTGRES, {"encrypted": 1}, id="postgres-flag-int"),
        pytest.param(Dialect.POSTGRES, {"updated_at": _T1_TEXT}, id="postgres-timestamp-text"),
    ],
)
def test_row_to_info_raises_backend_error_for_corrupt_columns(
    dialect: Dialect, overrides: dict[str, object]
) -> None:
    with pytest.raises(BackendError, match="store '"):
        row_to_info(_info_row(_SEALED, dialect, **overrides), dialect=dialect)
