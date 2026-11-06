"""`StoreSession`: what the TUI screens do with the library (PD 29, D7)."""

from pathlib import Path

import pytest

from environment_store.core.errors import (
    ConcurrentModificationError,
    DecryptionError,
    KeySourceError,
    StoreNotFoundError,
    VariableExistsError,
)
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.library.keys import generate_key_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.session import OpenedStore, StoreSession


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "a.key"
    generate_key_file(path)
    return path


def test_stores_lists_every_store_by_name(store: EnvironmentStore) -> None:
    store.create_store("b")
    store.create_store("a")

    names = [info.name for info in StoreSession(store, key_paths={}).stores()]

    assert names == ["a", "b"]


def test_open_reads_the_variables_and_the_revision(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set("a", "HOST", "localhost")

    opened = StoreSession(store, key_paths={}).open("a")

    assert opened.name == "a"
    assert dict(opened.variables) == {"HOST": "localhost"}
    assert opened.revision == store.store_info("a").revision


def test_open_a_missing_store_raises_not_found(store: EnvironmentStore) -> None:
    with pytest.raises(StoreNotFoundError):
        StoreSession(store, key_paths={}).open("missing")


def test_opened_store_repr_shows_neither_values_nor_secret(store: EnvironmentStore) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="pw-secret"))
    store.set("a", "TOKEN", "value-secret", key=Passphrase(text="pw-secret"))

    opened = StoreSession(store, key_paths={}).open("a", Passphrase(text="pw-secret"))

    assert "value-secret" not in repr(opened)
    assert "pw-secret" not in repr(opened)


def test_project_key_returns_the_path_of_the_project_file(
    store: EnvironmentStore, key: Path
) -> None:
    session = StoreSession(store, key_paths={"a": key})

    assert session.project_key("a") == key
    assert session.project_key("b") is None


def test_secret_from_file_reads_the_key_file(store: EnvironmentStore, key: Path) -> None:
    store.create_store("a", encrypt=True, key=key)

    secret = StoreSession(store, key_paths={}).secret_from_file("a", key)

    assert isinstance(secret, KeyMaterial)


def test_secret_from_file_uses_the_injected_reader(store: EnvironmentStore) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="pw"))
    read: list[Path] = []

    def read_key_file(path: Path) -> str:
        read.append(path)
        return "pw\n"

    session = StoreSession(store, key_paths={}, read_key_file=read_key_file)
    secret = session.secret_from_file("a", Path("p.txt"))

    assert read == [Path("p.txt")]
    assert secret == Passphrase(text="pw")


def test_secret_from_file_expands_the_home_directory(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    store.create_store("a", encrypt=True, key=key)

    secret = StoreSession(store, key_paths={}).secret_from_file("a", Path("~/a.key"))

    assert isinstance(secret, KeyMaterial)


def test_secret_from_a_missing_file_raises_key_source_error(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="pw"))

    with pytest.raises(KeySourceError):
        StoreSession(store, key_paths={}).secret_from_file("a", tmp_path / "missing")


def test_secret_from_text_is_a_passphrase_for_a_passphrase_store(store: EnvironmentStore) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="pw"))

    assert StoreSession(store, key_paths={}).secret_from_text("a", "pw") == Passphrase(text="pw")


def test_open_with_a_wrong_secret_raises_decryption_error(store: EnvironmentStore) -> None:
    store.create_store("a", encrypt=True, key=Passphrase(text="pw"))

    with pytest.raises(DecryptionError):
        StoreSession(store, key_paths={}).open("a", Passphrase(text="wrong"))


def test_set_adds_a_variable_and_returns_the_reloaded_store(store: EnvironmentStore) -> None:
    store.create_store("a")
    session = StoreSession(store, key_paths={})

    opened = session.set(session.open("a"), "HOST", "localhost", overwrite=False)

    assert dict(opened.variables) == {"HOST": "localhost"}
    assert opened.revision == store.store_info("a").revision
    assert store.get("a", "HOST") == "localhost"


def test_set_without_overwrite_refuses_an_existing_variable(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set("a", "HOST", "old")
    session = StoreSession(store, key_paths={})

    with pytest.raises(VariableExistsError):
        session.set(session.open("a"), "HOST", "new", overwrite=False)


def test_set_with_overwrite_replaces_the_value_in_an_encrypted_store(
    store: EnvironmentStore,
) -> None:
    secret = Passphrase(text="pw")
    store.create_store("a", encrypt=True, key=secret)
    store.set("a", "HOST", "old", key=secret)
    session = StoreSession(store, key_paths={})

    opened = session.set(session.open("a", secret), "HOST", "new", overwrite=True)

    assert dict(opened.variables) == {"HOST": "new"}
    assert store.get("a", "HOST", key=secret) == "new"


def test_delete_removes_a_variable(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set_many("a", {"A": "1", "B": "2"})
    session = StoreSession(store, key_paths={})

    opened = session.delete(session.open("a"), "A")

    assert dict(opened.variables) == {"B": "2"}
    assert store.variables("a") == {"B": "2"}


def test_reload_reads_the_current_state(store: EnvironmentStore, other: EnvironmentStore) -> None:
    store.create_store("a")
    session = StoreSession(store, key_paths={})
    opened = session.open("a")
    other.set("a", "NEW", "1")

    reloaded = session.reload(opened)

    assert dict(reloaded.variables) == {"NEW": "1"}


def _changed_elsewhere(
    store: EnvironmentStore, other: EnvironmentStore
) -> tuple[StoreSession, OpenedStore]:
    store.create_store("a")
    store.set("a", "KEEP", "1")
    session = StoreSession(store, key_paths={})
    opened = session.open("a")
    other.set("a", "OTHER", "2")
    return session, opened


def test_set_after_a_change_elsewhere_raises_conflict_and_writes_nothing(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    session, opened = _changed_elsewhere(store, other)

    with pytest.raises(ConcurrentModificationError, match="reload"):
        session.set(opened, "MINE", "3", overwrite=False)

    assert store.variables("a") == {"KEEP": "1", "OTHER": "2"}


def test_delete_after_a_change_elsewhere_raises_conflict_and_writes_nothing(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    session, opened = _changed_elsewhere(store, other)

    with pytest.raises(ConcurrentModificationError):
        session.delete(opened, "KEEP")

    assert store.variables("a") == {"KEEP": "1", "OTHER": "2"}
