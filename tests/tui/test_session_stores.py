"""`StoreSession` store management and export (D55, D56, D21, D52, D53, PD 4)."""

import json
import stat
from pathlib import Path
from typing import override

import pytest

from environment_store.core.adapter import SetupMode
from environment_store.core.errors import (
    BackendError,
    DecryptionError,
    InvalidKeyFileError,
    NotEncryptedError,
    StoreExistsError,
    ValidationError,
)
from environment_store.core.models import KeyMode, StoreInfo, StoreRecord
from environment_store.core.secrets import Passphrase
from environment_store.formats.infer import Format
from environment_store.library.files import OutputFileExistsError
from environment_store.library.keys import generate_key_file
from environment_store.library.sources import Source
from environment_store.library.store import EnvironmentStore
from environment_store.tui.choices import ExportOptions, GenerateKey, KeyFile, TypedPassphrase
from environment_store.tui.session import StoreSession
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend


@pytest.fixture
def session(store: EnvironmentStore) -> StoreSession:
    return StoreSession(store, key_paths={})


def test_create_store_without_a_key_creates_a_plain_store(
    session: StoreSession, store: EnvironmentStore
) -> None:
    info = session.create_store("a", None)

    assert info.name == "a"
    assert not store.store_info("a").encrypted


def test_create_store_with_an_existing_key_file_uses_it(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    key = tmp_path / "a.key"
    generate_key_file(key)

    session.create_store("a", KeyFile(key))

    assert store.store_info("a").key_mode is KeyMode.KEYFILE
    store.set("a", "X", "1", key=key)


def test_create_store_with_a_file_that_is_no_key_file_fails(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("not a key\n")

    with pytest.raises(InvalidKeyFileError):
        session.create_store("a", KeyFile(text))
    assert store.list_stores() == []


def test_create_store_with_a_passphrase_uses_it(
    session: StoreSession, store: EnvironmentStore
) -> None:
    session.create_store("a", TypedPassphrase(Passphrase(text="pw")))

    assert store.store_info("a").key_mode is KeyMode.PASSPHRASE
    store.set("a", "X", "1", key=Passphrase(text="pw"))


def test_create_store_generates_a_0600_key_file_and_uses_it(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    path = tmp_path / "new.key"

    session.create_store("a", GenerateKey(path))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store.set("a", "X", "1", key=path)


def test_create_store_never_overwrites_an_existing_file_for_a_new_key(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    path = tmp_path / "taken.key"
    path.write_text("keep me")

    with pytest.raises(ValidationError, match="already exists"):
        session.create_store("a", GenerateKey(path))
    assert path.read_text() == "keep me"
    assert store.list_stores() == []


def test_create_store_with_an_invalid_name_generates_no_key_file(
    session: StoreSession, tmp_path: Path
) -> None:
    path = tmp_path / "new.key"

    with pytest.raises(ValidationError):
        session.create_store("Bad Name", GenerateKey(path))
    assert not path.exists()


def test_create_store_that_exists_removes_the_generated_key_file(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("a")
    path = tmp_path / "new.key"

    with pytest.raises(StoreExistsError):
        session.create_store("a", GenerateKey(path))
    assert not path.exists()


class _FailingAdapter(MemoryAdapter):
    """Commits a new store, then reports a failure; optionally cannot list stores either."""

    list_fails: bool = False

    @override
    def create_store(self, record: StoreRecord) -> None:
        super().create_store(record)
        message = "connection lost"
        raise BackendError(message)

    @override
    def list_stores(self) -> list[StoreInfo]:
        if self.list_fails:
            message = "connection lost"
            raise BackendError(message)
        return super().list_stores()


def _failing_store(*, list_fails: bool) -> EnvironmentStore:
    backend = MemoryBackend()

    def opener(url: str, setup: SetupMode) -> MemoryAdapter:
        adapter = _FailingAdapter(backend, setup=setup)
        adapter.list_fails = list_fails
        return adapter

    return EnvironmentStore("memory://t", opener=opener, kdf_params_factory=CheapKdf())


@pytest.mark.parametrize("list_fails", [False, True])
def test_create_store_keeps_a_generated_key_file_the_store_may_use(
    tmp_path: Path, *, list_fails: bool
) -> None:
    path = tmp_path / "new.key"
    with _failing_store(list_fails=list_fails) as failing:
        session = StoreSession(failing, key_paths={})

        with pytest.raises(BackendError) as raised:
            session.create_store("a", GenerateKey(path))

    assert path.exists()
    assert str(raised.value) == (
        f"connection lost; kept the generated key file '{path}': store 'a' may already be "
        "encrypted with it"
    )


def test_delete_store_needs_no_key(
    session: StoreSession, store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="lost"))

    session.delete_store("a")

    assert store.list_stores() == []


def test_ordered_overwrite_defaults_to_last_wins(store: EnvironmentStore) -> None:
    assert StoreSession(store, key_paths={}).ordered_overwrite
    assert not StoreSession(store, key_paths={}, ordered_overwrite=False).ordered_overwrite


@pytest.fixture
def two_stores(store: EnvironmentStore) -> EnvironmentStore:
    store.create_store("base")
    store.set_many("base", {"HOST": "base-host", "B_ONLY": "b"})
    store.create_store("app")
    store.set_many("app", {"HOST": "app-host", "A_ONLY": "a"})
    return store


_LAST_WINS = ExportOptions(fmt=Format.JSON, nested=False, first_wins=False)


@pytest.mark.usefixtures("two_stores")
def test_export_writes_the_merged_stores_in_load_order_with_mode_0600(
    session: StoreSession, tmp_path: Path
) -> None:
    path = tmp_path / "out.json"

    session.export([Source("base"), Source("app")], path, _LAST_WINS, force=False)

    assert list(json.loads(path.read_text()).items()) == [
        ("B_ONLY", "b"),
        ("HOST", "app-host"),
        ("A_ONLY", "a"),
    ]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.usefixtures("two_stores")
def test_export_first_wins_keeps_the_first_value(session: StoreSession, tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    options = ExportOptions(fmt=Format.JSON, nested=False, first_wins=True)

    session.export([Source("base"), Source("app")], path, options, force=False)

    assert json.loads(path.read_text())["HOST"] == "base-host"


@pytest.mark.usefixtures("two_stores")
def test_export_nested_dotenv_prefixes_the_store_names(
    session: StoreSession, tmp_path: Path
) -> None:
    path = tmp_path / "out"
    options = ExportOptions(fmt=Format.DOTENV, nested=True, first_wins=False)

    session.export([Source("app")], path, options, force=False)

    assert path.read_text() == "APP__A_ONLY=a\nAPP__HOST=app-host\n"


@pytest.mark.usefixtures("two_stores")
def test_export_refuses_an_existing_file_without_force(
    session: StoreSession, tmp_path: Path
) -> None:
    path = tmp_path / "out.json"
    path.write_text("old")

    with pytest.raises(OutputFileExistsError):
        session.export([Source("base")], path, _LAST_WINS, force=False)
    assert path.read_text() == "old"

    session.export([Source("base")], path, _LAST_WINS, force=True)
    assert json.loads(path.read_text()) == {"B_ONLY": "b", "HOST": "base-host"}


def test_export_decrypts_with_the_given_secret(store: EnvironmentStore, tmp_path: Path) -> None:
    secret = Passphrase(text="pw")
    store.create_store("enc", encrypt=True, key=secret)
    store.set("enc", "TOKEN", "t", key=secret)
    path = tmp_path / "out.json"

    StoreSession(store, key_paths={}).export(
        [Source("enc", key=secret)], path, _LAST_WINS, force=False
    )

    assert json.loads(path.read_text()) == {"TOKEN": "t"}


def test_export_with_a_wrong_secret_writes_nothing(store: EnvironmentStore, tmp_path: Path) -> None:
    store.create_store("enc", encrypt=True, key=Passphrase(text="pw"))
    path = tmp_path / "out.json"

    with pytest.raises(DecryptionError):
        StoreSession(store, key_paths={}).export(
            [Source("enc", key=Passphrase(text="wrong"))], path, _LAST_WINS, force=False
        )
    assert not path.exists()


def test_export_refuses_a_project_key_for_a_plain_store(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("base")
    session = StoreSession(store, key_paths={"base": tmp_path / "base.key"})

    with pytest.raises(NotEncryptedError, match="names a key for store 'base'"):
        session.export([Source("base")], tmp_path / "out.json", _LAST_WINS, force=False)
