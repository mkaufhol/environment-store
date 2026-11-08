"""Export keys in the TUI: key variable, project key, unlock dialog, in this order."""

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest
from textual.pilot import Pilot

from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_file, generate_key_text
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.paths import PathInput
from environment_store.tui.screens.stores import StoresScreen
from environment_store.tui.screens.unlock import UnlockScreen
from tests.support.kdf import CheapKdf
from tests.tui.export_steps import export_to
from tests.tui.pilot import notifications, run_app, set_input


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "enc.key"
    generate_key_file(path)
    return path


@contextmanager
def _encrypted(
    connection: str, key: Path, environ: Mapping[str, str]
) -> Generator[EnvironmentStore]:
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf(), environ=environ) as opened:
        opened.create_store("enc", encrypt=True, key=key)
        opened.set("enc", "TOKEN", "secret-token", key=key)
        opened.create_store("plain")
        opened.set("plain", "HOST", "h")
        yield opened


def test_an_encrypted_store_takes_its_key_from_the_environment(
    connection: str, key: Path, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "plain", "enc")
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == ["exported to 'out.json'"]

    with _encrypted(connection, key, {"ENV_STORE_KEY_ENC": key.read_text()}) as store:
        run_app(store, scenario)
    assert json.loads((tmp_path / "out.json").read_text()) == {"HOST": "h", "TOKEN": "secret-token"}


def test_stores_sharing_a_set_key_variable_are_refused(connection: str, key: Path) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc-a", "enc_a")
        [message] = notifications(app)
        assert "ENV_STORE_KEY_ENC_A" in message
        assert "unclear which store" in message

    environ = {"ENV_STORE_KEY_ENC_A": key.read_text()}
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf(), environ=environ) as store:
        store.create_store("enc-a", encrypt=True, key=key)
        store.create_store("enc_a", encrypt=True, key=key)
        run_app(store, scenario)


def test_an_encrypted_store_takes_its_key_from_the_project_file(
    connection: str, key: Path, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc")
        assert notifications(app) == ["exported to 'out.json'"]

    with _encrypted(connection, key, {}) as store:
        run_app(store, scenario, key_paths={"enc": key})
    assert json.loads((tmp_path / "out.json").read_text()) == {"TOKEN": "secret-token"}


def test_an_encrypted_store_without_a_known_key_is_unlocked_in_the_dialog(
    connection: str, key: Path, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc", "plain")
        assert isinstance(app.screen, UnlockScreen)
        assert isinstance(app.screen.query_one("#path"), PathInput)
        await set_input(pilot, "#path", str(key))
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == ["exported to 'out.json'"]

    with _encrypted(connection, key, {}) as store:
        run_app(store, scenario)
    assert list(json.loads((tmp_path / "out.json").read_text())) == ["TOKEN", "HOST"]


def test_a_wrong_key_in_the_environment_falls_back_to_the_dialog(
    connection: str, key: Path, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc")
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith("unlocking with ENV_STORE_KEY_ENC failed: ")
        await set_input(pilot, "#path", str(key))
        await pilot.press("enter")
        await pilot.pause()

    with _encrypted(connection, key, {"ENV_STORE_KEY_ENC": generate_key_text()}) as store:
        run_app(store, scenario)
    assert json.loads((tmp_path / "out.json").read_text()) == {"TOKEN": "secret-token"}


def test_cancelling_the_unlock_dialog_writes_nothing(
    connection: str, key: Path, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == []

    with _encrypted(connection, key, {}) as store:
        run_app(store, scenario)
    assert not (tmp_path / "out.json").exists()


def test_a_passphrase_store_is_unlocked_with_the_typed_passphrase(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("p", encrypt=True, key=Passphrase(text="pw"))
    store.set("p", "TOKEN", "t", key=Passphrase(text="pw"))

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "p")
        await set_input(pilot, "#passphrase", "pw")
        await pilot.press("enter")
        await pilot.pause()

    run_app(store, scenario)
    assert json.loads((tmp_path / "out.json").read_text()) == {"TOKEN": "t"}


def test_a_file_created_while_unlocking_is_not_replaced(
    connection: str, key: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out.json"

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "enc")
        assert isinstance(app.screen, UnlockScreen)
        out.write_text("theirs")
        await set_input(pilot, "#path", str(key))
        await pilot.press("enter")
        await pilot.pause()
        assert notifications(app) == [
            "output file 'out.json' already exists; export again and confirm replacing it"
        ]

    with _encrypted(connection, key, {}) as store:
        run_app(store, scenario)
    assert out.read_text() == "theirs"
