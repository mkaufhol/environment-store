import base64
import dataclasses
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, cast

import pytest

from environment_store.core.errors import UnsupportedFormatError, ValidationError
from environment_store.core.models import (
    MAX_REVISION,
    PAYLOAD_FORMAT_VERSION,
    Cipher,
    CipherMeta,
    KdfParams,
    KeyMode,
    Source,
    StoreInfo,
    StoreRecord,
)
from environment_store.core.secrets import KeyMaterial, Passphrase

_SALT = bytes(range(16))
_SALT_B64 = base64.b64encode(_SALT).decode("ascii")
_T0 = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 11, 6, 12, 30, 0, 123456, tzinfo=UTC)
_KEYFILE_META = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE)
_PASSPHRASE_META = CipherMeta(
    cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE, kdf=KdfParams(salt=_SALT)
)


def _kdf_json(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "name": "argon2id",
        "t": 3,
        "m": 65536,
        "p": 4,
        "salt": _SALT_B64,
    }
    document.update(overrides)
    return document


# --- constants and enums -----------------------------------------------------------------------


def test_payload_format_version_is_1() -> None:
    assert PAYLOAD_FORMAT_VERSION == 1


def test_v2_ships_a_single_cipher_aes256gcm() -> None:
    assert [cipher.value for cipher in Cipher] == ["aes256gcm"]


def test_key_modes_are_keyfile_and_passphrase() -> None:
    assert [mode.value for mode in KeyMode] == ["keyfile", "passphrase"]


# --- KdfParams ---------------------------------------------------------------------------------


def test_kdf_params_default_to_rfc_9106_second_recommendation() -> None:
    params = KdfParams(salt=_SALT)

    assert (params.name, params.iterations, params.memory_kib, params.lanes) == (
        "argon2id",
        3,
        65536,
        4,
    )


def test_kdf_params_accept_the_upper_bounds() -> None:
    params = KdfParams(iterations=10, memory_kib=1048576, lanes=16, salt=_SALT)

    assert (params.iterations, params.memory_kib, params.lanes) == (10, 1048576, 16)


def test_kdf_params_accept_the_lower_bounds() -> None:
    params = KdfParams(iterations=1, memory_kib=8, lanes=1, salt=_SALT)

    assert (params.iterations, params.memory_kib, params.lanes) == (1, 8, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("iterations", 0),
        ("iterations", 11),
        ("memory_kib", 1048577),
        ("memory_kib", 31),  # below 8 KiB per lane with the default 4 lanes
        ("lanes", 0),
        ("lanes", 17),
    ],
)
def test_kdf_params_reject_out_of_bounds_values(field: str, value: int) -> None:
    # Bounds protect against a tampered store forcing a huge Argon2id computation.
    with pytest.raises(UnsupportedFormatError, match=field):
        KdfParams(salt=_SALT, **{field: value})  # ty: ignore[invalid-argument-type] - wrong types on purpose


@pytest.mark.parametrize("field", ["iterations", "memory_kib", "lanes"])
@pytest.mark.parametrize("value", [True, 3.0, "3"])
def test_kdf_params_reject_non_integer_values(field: str, value: object) -> None:
    with pytest.raises(UnsupportedFormatError, match=f"{field} must be an integer"):
        KdfParams(salt=_SALT, **{field: value})  # ty: ignore[invalid-argument-type] - wrong types on purpose


def test_kdf_params_reject_unknown_kdf_names() -> None:
    with pytest.raises(UnsupportedFormatError, match="unsupported KDF 'scrypt'"):
        KdfParams(name=cast("Literal['argon2id']", "scrypt"), salt=_SALT)


@pytest.mark.parametrize("length", [0, 8, 15, 17, 32])
def test_kdf_params_require_a_16_byte_salt(length: int) -> None:
    with pytest.raises(UnsupportedFormatError, match="salt must be 16 bytes"):
        KdfParams(salt=b"s" * length)


def test_kdf_params_reject_a_non_bytes_salt() -> None:
    with pytest.raises(UnsupportedFormatError, match="salt must be 16 bytes"):
        KdfParams(salt=cast("bytes", _SALT_B64))


def test_kdf_params_to_json_uses_the_short_t_m_p_keys() -> None:
    assert KdfParams(salt=_SALT).to_json() == _kdf_json()


def test_kdf_params_from_json_reads_the_short_t_m_p_keys() -> None:
    params = KdfParams.from_json(_kdf_json(t=2, m=1024, p=2))

    assert params == KdfParams(iterations=2, memory_kib=1024, lanes=2, salt=_SALT)


def test_kdf_params_round_trip_through_json() -> None:
    params = KdfParams(iterations=4, memory_kib=4096, lanes=8, salt=b"\xff" * 16)

    assert KdfParams.from_json(params.to_json()) == params


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (["argon2id"], "KDF parameters must be an object"),
        (None, "KDF parameters must be an object"),
        ({k: v for k, v in _kdf_json().items() if k != "salt"}, "missing: salt"),
        (_kdf_json(extra=1), "unknown: extra"),
        (_kdf_json(name="scrypt"), "unsupported KDF 'scrypt'"),
        (_kdf_json(name=1), "unsupported KDF 1"),
        (_kdf_json(t="3"), "iterations must be an integer"),
        (_kdf_json(t=99), "iterations"),
        (_kdf_json(m=2**40), "memory_kib"),
        (_kdf_json(p=None), "lanes must be an integer"),
        (_kdf_json(salt=16), "salt must be a base64 string"),
        (_kdf_json(salt="not base64!"), "salt must be a base64 string"),
        (_kdf_json(salt="äöü"), "salt must be a base64 string"),
        (_kdf_json(salt=base64.b64encode(b"short").decode()), "salt must be 16 bytes"),
    ],
)
def test_kdf_params_from_json_rejects_invalid_documents(document: object, message: str) -> None:
    with pytest.raises(UnsupportedFormatError, match=message):
        KdfParams.from_json(document)


# --- CipherMeta --------------------------------------------------------------------------------


def test_keyfile_cipher_meta_has_no_kdf() -> None:
    assert _KEYFILE_META.to_json() == {"cipher": "aes256gcm", "mode": "keyfile"}


def test_passphrase_cipher_meta_includes_its_kdf() -> None:
    assert _PASSPHRASE_META.to_json() == {
        "cipher": "aes256gcm",
        "mode": "passphrase",
        "kdf": _kdf_json(),
    }


@pytest.mark.parametrize("meta", [_KEYFILE_META, _PASSPHRASE_META])
def test_cipher_meta_round_trips_through_json(meta: CipherMeta) -> None:
    assert CipherMeta.from_json(meta.to_json()) == meta


def test_cipher_meta_from_json_returns_enum_members() -> None:
    meta = CipherMeta.from_json({"cipher": "aes256gcm", "mode": "keyfile"})

    assert meta.cipher is Cipher.AES256GCM
    assert meta.mode is KeyMode.KEYFILE


def test_passphrase_cipher_meta_requires_kdf_params() -> None:
    with pytest.raises(UnsupportedFormatError, match="passphrase mode requires KDF parameters"):
        CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE)


def test_keyfile_cipher_meta_rejects_kdf_params() -> None:
    with pytest.raises(UnsupportedFormatError, match="keyfile mode takes no KDF parameters"):
        CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE, kdf=KdfParams(salt=_SALT))


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"cipher": "aes256gcm", "mode": KeyMode.KEYFILE}, "cipher must be a Cipher"),
        ({"cipher": Cipher.AES256GCM, "mode": "keyfile"}, "mode must be a KeyMode"),
        (
            {"cipher": Cipher.AES256GCM, "mode": KeyMode.PASSPHRASE, "kdf": _kdf_json()},
            "kdf must be KdfParams",
        ),
    ],
)
def test_cipher_meta_rejects_wrongly_typed_fields(
    fields: Mapping[str, object], message: str
) -> None:
    with pytest.raises(UnsupportedFormatError, match=message):
        CipherMeta(**fields)  # ty: ignore[invalid-argument-type] - wrong types on purpose


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("aes256gcm", "cipher metadata must be an object"),
        ({"mode": "keyfile"}, "missing: cipher"),
        ({"cipher": "aes256gcm"}, "missing: mode"),
        ({"cipher": "aes256gcm", "mode": "keyfile", "x": 1}, "unknown: x"),
        ({"cipher": "chacha20", "mode": "keyfile"}, "unsupported cipher 'chacha20'"),
        ({"cipher": "AES256GCM", "mode": "keyfile"}, "unsupported cipher 'AES256GCM'"),
        ({"cipher": 1, "mode": "keyfile"}, "unsupported cipher 1"),
        ({"cipher": "aes256gcm", "mode": "age"}, "unsupported key mode 'age'"),
        ({"cipher": "aes256gcm", "mode": "passphrase"}, "requires KDF parameters"),
        (
            {"cipher": "aes256gcm", "mode": "keyfile", "kdf": _kdf_json()},
            "keyfile mode takes no KDF parameters",
        ),
        ({"cipher": "aes256gcm", "mode": "passphrase", "kdf": None}, "must be an object"),
        ({"cipher": "aes256gcm", "mode": "passphrase", "kdf": _kdf_json(t=0)}, "iterations"),
    ],
)
def test_cipher_meta_from_json_rejects_invalid_documents(document: object, message: str) -> None:
    with pytest.raises(UnsupportedFormatError, match=message):
        CipherMeta.from_json(document)


@pytest.mark.parametrize("meta", [_KEYFILE_META, _PASSPHRASE_META])
def test_cipher_meta_file_table_uses_the_store_file_keys(meta: CipherMeta) -> None:
    table = meta.to_file_table()

    assert table == {
        "name": "aes256gcm",
        **{k: v for k, v in meta.to_json().items() if k != "cipher"},
    }


def test_cipher_meta_reads_the_store_file_cipher_table() -> None:
    table = tomllib.loads('[cipher]\nname = "aes256gcm"\nmode = "keyfile"\n')["cipher"]

    assert CipherMeta.from_file_table(table) == _KEYFILE_META


@pytest.mark.parametrize("meta", [_KEYFILE_META, _PASSPHRASE_META])
def test_cipher_meta_round_trips_through_the_file_table(meta: CipherMeta) -> None:
    assert CipherMeta.from_file_table(meta.to_file_table()) == meta


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("aes256gcm", "cipher table must be an object"),
        ({"mode": "keyfile"}, "missing: name"),
        ({"name": "aes256gcm", "cipher": "aes256gcm", "mode": "keyfile"}, "unknown: cipher"),
        ({"name": "aes256gcm", "mode": "keyfile", "x": 1}, "unknown: x"),
        ({"name": "chacha20", "mode": "keyfile"}, "unsupported cipher 'chacha20'"),
        ({"name": "aes256gcm", "mode": "passphrase"}, "requires KDF parameters"),
    ],
)
def test_cipher_meta_from_file_table_rejects_invalid_documents(
    document: object, message: str
) -> None:
    with pytest.raises(UnsupportedFormatError, match=message):
        CipherMeta.from_file_table(document)


# --- StoreInfo ---------------------------------------------------------------------------------


def _info(**overrides: object) -> StoreInfo:
    fields: dict[str, object] = {
        "name": "base",
        "encrypted": True,
        "key_mode": KeyMode.KEYFILE,
        "revision": 1,
        "created_at": _T0,
        "updated_at": _T1,
    }
    fields.update(overrides)
    return StoreInfo(**fields)


def test_store_info_holds_listing_fields() -> None:
    info = _info()

    assert (info.name, info.encrypted, info.key_mode, info.revision) == (
        "base",
        True,
        KeyMode.KEYFILE,
        1,
    )
    assert (info.created_at, info.updated_at) == (_T0, _T1)


def test_store_info_key_mode_may_be_unknown_for_encrypted_stores() -> None:
    # Adapters list stores whose cipher metadata this version does not recognise.
    assert _info(key_mode=None).key_mode is None


def test_store_info_of_a_plaintext_store_has_no_key_mode() -> None:
    with pytest.raises(ValidationError, match="plaintext store has no key mode"):
        _info(encrypted=False)


def test_store_info_validates_the_store_name() -> None:
    with pytest.raises(ValidationError, match="invalid store name"):
        _info(name="../etc")


@pytest.mark.parametrize("encrypted", ["no", 0, 1, None])
def test_store_info_encrypted_must_be_a_bool(encrypted: object) -> None:
    with pytest.raises(ValidationError, match="encrypted must be a bool"):
        _info(encrypted=encrypted, key_mode=None)


@pytest.mark.parametrize("key_mode", ["bogus", "keyfile", 1])
def test_store_info_key_mode_must_be_a_key_mode_or_none(key_mode: object) -> None:
    with pytest.raises(ValidationError, match="key_mode must be a KeyMode member or None"):
        _info(key_mode=key_mode)


def test_store_info_validates_the_revision() -> None:
    with pytest.raises(ValidationError, match="revision"):
        _info(revision=0)


def test_max_revision_is_the_largest_sql_integer() -> None:
    # The SQL schema stores the revision as a 32-bit INTEGER, the narrowest backend.
    assert MAX_REVISION == 2**31 - 1


def test_store_info_and_record_accept_the_largest_revision() -> None:
    assert _info(revision=MAX_REVISION).revision == MAX_REVISION
    assert _plain(revision=MAX_REVISION).revision == MAX_REVISION


@pytest.mark.parametrize("revision", [MAX_REVISION + 1, 2**63])
def test_store_info_and_record_reject_a_revision_beyond_the_largest(revision: int) -> None:
    with pytest.raises(
        ValidationError, match=f"revision must be an integer >= 1 and <= {MAX_REVISION}"
    ):
        _info(revision=revision)
    with pytest.raises(
        ValidationError, match=f"revision must be an integer >= 1 and <= {MAX_REVISION}"
    ):
        _plain(revision=revision)


def test_store_info_timestamps_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _info(created_at=_T0.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", datetime(1, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=1)))),
        ("updated_at", datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-1)))),
    ],
    ids=["before-utc-min", "after-utc-max"],
)
def test_timestamps_without_a_utc_equivalent_raise_validation_error(
    field: str, value: datetime
) -> None:
    with pytest.raises(ValidationError, match=f"{field} is out of range"):
        _info(**{field: value})
    with pytest.raises(ValidationError, match=f"{field} is out of range"):
        _plain(**{field: value})


def test_store_info_created_at_must_not_be_after_updated_at() -> None:
    with pytest.raises(ValidationError, match="created_at must not be after updated_at"):
        _info(created_at=_T1, updated_at=_T0)


# --- StoreRecord -------------------------------------------------------------------------------


def _plain(**overrides: object) -> StoreRecord:
    fields: dict[str, object] = {
        "name": "base",
        "revision": 1,
        "created_at": _T0,
        "updated_at": _T1,
        "variables": {"DB_HOST": "localhost"},
    }
    fields.update(overrides)
    return StoreRecord(**fields)  # ty: ignore[invalid-argument-type] - wrong types on purpose


def test_plain_constructor_builds_an_unencrypted_record() -> None:
    record = StoreRecord.plain(name="base", variables={"A": "1"}, created_at=_T0)

    assert record.encrypted is False
    assert record.variables == {"A": "1"}
    assert record.ciphertext is None
    assert record.cipher_meta is None


def test_plain_constructor_defaults_to_revision_1_and_updated_equals_created() -> None:
    record = StoreRecord.plain(name="base", variables={}, created_at=_T0)

    assert record.revision == 1
    assert record.updated_at == record.created_at == _T0


def test_sealed_constructor_builds_an_encrypted_record() -> None:
    record = StoreRecord.sealed(
        name="secrets",
        ciphertext=b"\x00\x01opaque",
        cipher_meta=_PASSPHRASE_META,
        revision=7,
        created_at=_T0,
        updated_at=_T1,
    )

    assert record.encrypted is True
    assert record.variables is None
    assert record.ciphertext == b"\x00\x01opaque"
    assert record.cipher_meta == _PASSPHRASE_META
    assert (record.revision, record.created_at, record.updated_at) == (7, _T0, _T1)


def test_sealed_constructor_defaults_to_revision_1_and_updated_equals_created() -> None:
    record = StoreRecord.sealed(
        name="secrets", ciphertext=b"", cipher_meta=_KEYFILE_META, created_at=_T0
    )

    assert record.revision == 1
    assert record.updated_at == _T0


def test_record_variables_are_an_immutable_copy() -> None:
    source = {"A": "1"}
    record = _plain(variables=source)

    source["B"] = "2"

    assert record.variables == {"A": "1"}
    with pytest.raises(TypeError):
        cast("dict[str, str]", record.variables)["C"] = "3"


def test_record_variables_are_in_code_point_order_whatever_the_input_order() -> None:
    # Every backend then returns the same order (JSONB, for one, reorders keys).
    record = _plain(variables={"ZZ": "1", "a": "2", "B_LONGER": "3", "AAA": "4", "_": "5"})

    assert list(record.variables or {}) == ["AAA", "B_LONGER", "ZZ", "_", "a"]


def test_record_is_frozen() -> None:
    record = _plain()

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.revision = 2  # ty: ignore[invalid-assignment] - asserting the runtime guard


def test_records_with_equal_fields_are_equal() -> None:
    assert _plain() == _plain(variables={"DB_HOST": "localhost"})


def test_record_repr_never_shows_variables_or_ciphertext() -> None:
    plain = _plain(variables={"TOKEN": "s3cr3t-value"})
    sealed = StoreRecord.sealed(
        name="x", ciphertext=b"CIPHERBYTES", cipher_meta=_KEYFILE_META, created_at=_T0
    )

    assert "s3cr3t-value" not in repr(plain)
    assert "CIPHERBYTES" not in repr(sealed)


def test_plain_record_info_has_no_key_mode() -> None:
    assert _plain(revision=3).info == StoreInfo(
        name="base", encrypted=False, key_mode=None, revision=3, created_at=_T0, updated_at=_T1
    )


def test_sealed_record_info_reports_the_key_mode() -> None:
    record = StoreRecord.sealed(
        name="secrets", ciphertext=b"x", cipher_meta=_PASSPHRASE_META, created_at=_T0
    )

    assert record.info == StoreInfo(
        name="secrets",
        encrypted=True,
        key_mode=KeyMode.PASSPHRASE,
        revision=1,
        created_at=_T0,
        updated_at=_T0,
    )


@pytest.mark.parametrize("name", ["", "Base", "../x", "a/b"])
def test_record_rejects_invalid_store_names(name: str) -> None:
    with pytest.raises(ValidationError, match="invalid store name"):
        _plain(name=name)


@pytest.mark.parametrize("revision", [0, -1, True, 1.0, "1"])
def test_record_revision_must_be_a_positive_integer(revision: object) -> None:
    with pytest.raises(ValidationError, match="revision must be an integer >= 1"):
        _plain(revision=revision)


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_record_timestamps_must_be_timezone_aware(field: str) -> None:
    with pytest.raises(ValidationError, match=f"{field} must be a timezone-aware datetime"):
        _plain(**{field: datetime(2026, 11, 6)})  # noqa: DTZ001 - naive on purpose


def test_record_timestamps_must_be_datetimes() -> None:
    with pytest.raises(ValidationError, match="created_at must be a timezone-aware datetime"):
        _plain(created_at="2026-11-06T10:00:00Z")


def test_record_timestamps_are_normalised_to_utc() -> None:
    cest = timezone(timedelta(hours=2))
    record = _plain(created_at=_T0.astimezone(cest), updated_at=_T1.astimezone(cest))

    assert record.created_at.tzinfo is UTC
    assert record.updated_at.tzinfo is UTC
    assert (record.created_at, record.updated_at) == (_T0, _T1)


def test_record_keeps_microseconds() -> None:
    assert _plain().updated_at.microsecond == 123456


def test_record_created_at_must_not_be_after_updated_at() -> None:
    with pytest.raises(ValidationError, match="created_at must not be after updated_at"):
        _plain(created_at=_T1, updated_at=_T0)


def test_record_rejects_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="invalid variable name"):
        _plain(variables={"1BAD": "x"})


def test_record_rejects_nul_in_variable_values() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        _plain(variables={"GOOD": "x\x00"})


def test_record_variables_must_be_a_mapping() -> None:
    with pytest.raises(ValidationError, match="variables must be a mapping"):
        _plain(variables=[("A", "1")])


def test_record_needs_variables_or_ciphertext() -> None:
    with pytest.raises(ValidationError, match="either variables or ciphertext and cipher_meta"):
        _plain(variables=None)


def test_record_ciphertext_needs_cipher_meta() -> None:
    with pytest.raises(ValidationError, match="either variables or ciphertext and cipher_meta"):
        _plain(variables=None, ciphertext=b"x")


def test_record_cipher_meta_needs_ciphertext() -> None:
    with pytest.raises(ValidationError, match="either variables or ciphertext and cipher_meta"):
        _plain(variables=None, cipher_meta=_KEYFILE_META)


@pytest.mark.parametrize(
    "extra",
    [
        {"ciphertext": b"x"},
        {"cipher_meta": _KEYFILE_META},
        {"ciphertext": b"x", "cipher_meta": _KEYFILE_META},
    ],
)
def test_record_cannot_be_plaintext_and_encrypted(extra: Mapping[str, object]) -> None:
    with pytest.raises(ValidationError, match="not both"):
        _plain(**extra)


def test_record_ciphertext_must_be_bytes() -> None:
    with pytest.raises(ValidationError, match="ciphertext must be bytes"):
        _plain(variables=None, ciphertext="x", cipher_meta=_KEYFILE_META)


def test_record_cipher_meta_must_be_cipher_meta() -> None:
    with pytest.raises(ValidationError, match="cipher_meta must be CipherMeta"):
        _plain(variables=None, ciphertext=b"x", cipher_meta=_KEYFILE_META.to_json())


def test_replace_builds_a_record_with_the_new_field() -> None:
    assert dataclasses.replace(_plain(), revision=2).revision == 2


def test_replace_revalidates_the_record() -> None:
    with pytest.raises(ValidationError, match="revision"):
        dataclasses.replace(_plain(), revision=0)


# --- Source ------------------------------------------------------------------------------------


def test_source_defaults_to_no_secret() -> None:
    assert Source(name="base").secret is None


def test_source_holds_a_secret() -> None:
    secret = Passphrase(text="pw")

    assert Source(name="base", secret=secret).secret is secret


def test_source_validates_the_store_name() -> None:
    with pytest.raises(ValidationError, match="invalid store name"):
        Source(name="../base")


def test_source_repr_redacts_the_secret() -> None:
    source = Source(name="base", secret=KeyMaterial(key=b"\xee" * 32))

    assert "<redacted>" in repr(source)
    assert "\\xee" not in repr(source)
