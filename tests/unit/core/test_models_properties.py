import json
import tomllib

from hypothesis import given

from environment_store._toml import dumps as toml_dumps
from environment_store.core.models import CipherMeta, StoreRecord
from tests.support.strategies import cipher_metas, plain_records, sealed_records


@given(cipher_metas())
def test_cipher_meta_round_trips_through_json_text(meta: CipherMeta) -> None:
    assert CipherMeta.from_json(json.loads(json.dumps(meta.to_json()))) == meta


@given(cipher_metas())
def test_cipher_meta_round_trips_through_toml_text(meta: CipherMeta) -> None:
    # The TOML file adapter stores the metadata as a [cipher] table.
    document = tomllib.loads(toml_dumps({"cipher": meta.to_json()}))

    assert CipherMeta.from_json(document["cipher"]) == meta


@given(plain_records())
def test_plain_record_info_mirrors_the_record(record: StoreRecord) -> None:
    info = record.info

    assert (info.name, info.encrypted, info.key_mode, info.revision) == (
        record.name,
        False,
        None,
        record.revision,
    )
    assert (info.created_at, info.updated_at) == (record.created_at, record.updated_at)


@given(sealed_records())
def test_sealed_record_info_reports_the_cipher_key_mode(record: StoreRecord) -> None:
    assert record.cipher_meta is not None
    assert record.info.key_mode is record.cipher_meta.mode
    assert record.info.encrypted


@given(plain_records())
def test_plain_record_rebuilt_from_its_fields_is_equal(record: StoreRecord) -> None:
    assert record.variables is not None
    rebuilt = StoreRecord.plain(
        name=record.name,
        variables=dict(record.variables),
        revision=record.revision,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )

    assert rebuilt == record
