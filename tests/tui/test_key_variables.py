"""The TUI and `ENV_STORE_KEY_<STORE>`: tried before the project key and the dialog (D53)."""

import dataclasses
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import pytest
from textual.pilot import Pilot
from typer.testing import CliRunner

import environment_store.tui
from environment_store.cli.app import app as envs
from environment_store.core.secrets import Passphrase, Secret
from environment_store.library.keys import generate_key_file, generate_key_text
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.stores import StoresScreen
from environment_store.tui.screens.unlock import UnlockScreen
from environment_store.tui.screens.variables import MASK, VariablesScreen
from environment_store.tui.session import StoreSession
from tests.support.cli import CliHarness, assert_exit
from tests.support.kdf import CheapKdf
from tests.tui.pilot import notifications, rows, run_app

CANARY: Final = "do-not-echo-this-value"


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "a.key"
    generate_key_file(path)
    return path


@pytest.fixture
def arranged(store: EnvironmentStore, key: Path) -> None:
    """Store `a` encrypted with `key` and plaintext store `b`."""
    store.create_store("a", encrypt=True, key=key)
    store.set("a", "API_URL", "hidden-value", key=key)
    store.create_store("b")
    store.set("b", "HOST", "plain")


@contextmanager
def _store(connection: str, environ: Mapping[str, str]) -> Generator[EnvironmentStore]:
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf(), environ=environ) as opened:
        yield opened


async def _open_first(pilot: Pilot[None]) -> None:
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.usefixtures("arranged")
def test_an_encrypted_store_opens_with_its_variable_before_the_project_key(
    connection: str, key: Path, tmp_path: Path
) -> None:
    wrong = tmp_path / "wrong.key"
    generate_key_file(wrong)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["API_URL", MASK]]
        assert notifications(app) == []

    with _store(connection, {"ENV_STORE_KEY_A": key.read_text(encoding="utf-8")}) as store:
        run_app(store, scenario, key_paths={"a": wrong})


@pytest.mark.usefixtures("arranged")
def test_a_wrong_key_in_the_variable_notifies_naming_it_and_asks(
    connection: str, key: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith("unlocking with ENV_STORE_KEY_A failed: cannot decrypt store 'a'")
        assert "hidden-value" not in message

    with _store(connection, {"ENV_STORE_KEY_A": generate_key_text()}) as store:
        run_app(store, scenario, key_paths={"a": key})


@pytest.mark.usefixtures("arranged")
def test_an_invalid_variable_notifies_without_the_value_and_asks(connection: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith("unlocking with ENV_STORE_KEY_A failed: ")
        assert CANARY not in message

    with _store(connection, {"ENV_STORE_KEY_A": CANARY}) as store:
        run_app(store, scenario)


@pytest.mark.usefixtures("arranged")
def test_the_variable_of_a_plaintext_store_is_ignored(connection: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("down", "enter")
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)
        assert notifications(app) == []

    with _store(connection, {"ENV_STORE_KEY_B": ""}) as store:
        run_app(store, scenario)


@pytest.mark.usefixtures("arranged")
def test_without_a_variable_or_project_key_the_dialog_asks(connection: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == []
        await pilot.press("escape")
        assert isinstance(app.screen, StoresScreen)

    with _store(connection, {}) as store:
        run_app(store, scenario)


@pytest.mark.usefixtures("arranged")
def test_the_session_reads_the_variable_through_the_library(connection: str) -> None:
    environ = {"ENV_STORE_KEY_A": "", "ENV_STORE_KEY_P": "pw"}
    with _store(connection, environ) as store:
        store.create_store("p", encrypt=True, key=Passphrase(text="pw"))
        session = StoreSession(store, key_paths={})

        assert session.environment_secret("p") == Passphrase(text="pw")
        assert session.environment_secret("b") is None


def test_envs_tui_gives_the_tui_a_store_with_the_cli_environment(
    cli_json: CliHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_json.store().create_store("p", encrypt=True, key=Passphrase(text="pw"))
    seen: list[Secret | None] = []

    def fake_run_tui(
        store: EnvironmentStore,
        *,
        key_paths: Mapping[str, Path],
        project_file: Path | None,
        ordered_overwrite: bool,
    ) -> None:
        seen.append(store.environment_secret("p"))

    monkeypatch.setattr(environment_store.tui, "run_tui", fake_run_tui)
    runtime = dataclasses.replace(
        cli_json.runtime(stdin_tty=True, stdout_tty=True),
        environ=lambda: {"ENV_STORE_KEY_P": "pw"},
    )

    result = CliRunner().invoke(envs, ["-c", cli_json.connection, "tui"], obj=runtime)

    assert_exit(result, 0)
    assert seen == [Passphrase(text="pw")]
