"""The on-disk layout of spec §3.2, pinned by hand-written golden files."""

import dataclasses
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from environment_store.adapters.files import JSON_SERIALIZER, TOML_SERIALIZER, FileSerializer
from environment_store.core.adapter import Adapter
from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode, StoreRecord
from tests.adapters.files.backend import FileBackend, Scheme

_GOLDEN: Final[Path] = Path(__file__).parent / "golden"
_T0: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
_T1: Final[datetime] = datetime(2026, 11, 6, 12, 30, 0, 250000, tzinfo=UTC)

_RECORDS: Final[dict[str, StoreRecord]] = {
    "base": StoreRecord.plain(
        name="base",
        # Written sorted by variable name, whatever the insertion order.
        variables={"MULTI": 'a\nb "q" ä', "DB_PORT": "5432", "DB_HOST": "localhost"},
        revision=3,
        created_at=_T0,
        updated_at=_T1,
    ),
    "secret": StoreRecord.sealed(
        name="secret",
        ciphertext=bytes(range(20)),
        cipher_meta=CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE),
        revision=7,
        created_at=_T0,
        updated_at=_T1,
    ),
    "vault": StoreRecord.sealed(
        name="vault",
        ciphertext=b"\xff" * 5,
        cipher_meta=CipherMeta(
            cipher=Cipher.AES256GCM,
            mode=KeyMode.PASSPHRASE,
            kdf=KdfParams(iterations=3, memory_kib=65536, lanes=4, salt=bytes(range(16))),
        ),
        revision=2,
        created_at=_T0,
        updated_at=_T1,
    ),
}
_CASES: Final = [
    pytest.param(name, scheme, id=f"{name}.{scheme}")
    for name in _RECORDS
    for scheme in ("json", "toml")
]


def _backend(tmp_path: Path, scheme: Scheme) -> FileBackend:
    return FileBackend(url=f"{scheme}://{tmp_path}", scheme=scheme)


def _store(adapter: Adapter, record: StoreRecord) -> None:
    """Bring a store to `record` through create and writes, as the service would."""
    previous = StoreRecord.plain(name=record.name, variables={}, created_at=record.created_at)
    adapter.create_store(previous)
    for revision in range(2, record.revision):
        current = StoreRecord.plain(
            name=record.name,
            variables={"STEP": str(revision)},
            revision=revision,
            created_at=record.created_at,
            updated_at=record.created_at + timedelta(seconds=revision),
        )
        adapter.write_store(current, expected_revision=previous.revision)
        previous = current
    adapter.write_store(record, expected_revision=previous.revision)


@pytest.mark.parametrize(("name", "scheme"), _CASES)
def test_adapter_writes_the_golden_layout(tmp_path: Path, name: str, scheme: Scheme) -> None:
    with _backend(tmp_path, scheme).open() as adapter:
        _store(adapter, _RECORDS[name])

    written = (tmp_path / f"{name}.{scheme}").read_text(encoding="utf-8")
    assert written == (_GOLDEN / f"{name}.{scheme}").read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "scheme"), _CASES)
def test_adapter_reads_the_golden_layout(tmp_path: Path, name: str, scheme: Scheme) -> None:
    shutil.copy(_GOLDEN / f"{name}.{scheme}", tmp_path)

    with _backend(tmp_path, scheme).open() as adapter:
        assert adapter.read_store(name) == _RECORDS[name]
        assert adapter.list_stores() == [_RECORDS[name].info]


@pytest.mark.parametrize(
    ("scheme", "cipher_table"),
    [
        ("json", '  "cipher": {\n    "name": "aes256gcm",\n'),
        ("toml", '[cipher]\nname = "aes256gcm"\n'),
    ],
)
def test_adapter_writes_a_cipher_table_naming_aes256gcm(
    tmp_path: Path, scheme: Scheme, cipher_table: str
) -> None:
    with _backend(tmp_path, scheme).open() as adapter:
        adapter.create_store(dataclasses.replace(_RECORDS["vault"], revision=1))

    assert cipher_table in (tmp_path / f"vault.{scheme}").read_text(encoding="utf-8")


def test_spec_json_example_is_read(tmp_path: Path) -> None:
    # Verbatim from spec §3.2.
    (tmp_path / "base.json").write_text(
        """{
  "format": 1,
  "encrypted": false,
  "revision": 3,
  "created_at": "2026-11-06T10:00:00Z",
  "updated_at": "2026-11-06T12:30:00Z",
  "variables": { "DB_HOST": "localhost", "DB_PORT": "5432" }
}
""",
        encoding="utf-8",
    )

    with _backend(tmp_path, "json").open() as adapter:
        record = adapter.read_store("base")

    assert record == StoreRecord.plain(
        name="base",
        variables={"DB_HOST": "localhost", "DB_PORT": "5432"},
        revision=3,
        created_at=_T0,
        updated_at=datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("serializer", "extension"), [(JSON_SERIALIZER, ".json"), (TOML_SERIALIZER, ".toml")]
)
def test_serializer_names_its_file_extension(serializer: FileSerializer, extension: str) -> None:
    assert serializer.extension == extension


@pytest.mark.parametrize("serializer", [JSON_SERIALIZER, TOML_SERIALIZER])
def test_serializer_round_trips_a_document_with_timestamps(serializer: FileSerializer) -> None:
    text = serializer.dumps({"at": _T1, "table": {"at": _T0, "n": 1, "flag": True}})

    loaded = serializer.loads(text)

    assert isinstance(loaded, dict)
    assert serializer.parse_timestamp(loaded["at"]) == _T1
    assert serializer.parse_timestamp(loaded["table"]["at"]) == _T0
    assert loaded["table"]["n"] == 1
    assert loaded["table"]["flag"] is True


@pytest.mark.parametrize("serializer", [JSON_SERIALIZER, TOML_SERIALIZER])
@pytest.mark.parametrize(
    "value",
    [None, 5, "", "2026-11-06", "2026-11-06T10:00:00", "not a time", datetime(2026, 1, 1)],  # noqa: DTZ001 - naive on purpose
    ids=["none", "int", "empty", "date", "naive-text", "garbage", "naive"],
)
def test_serializer_rejects_timestamps_without_an_offset(
    serializer: FileSerializer, value: object
) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        serializer.parse_timestamp(value)
