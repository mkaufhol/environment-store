"""Creating a store in the TUI: name checked as typed, every encryption, the no-save reminder."""

import stat
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Button, Input, Static

from environment_store.core.models import KeyMode
from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.paths import PathInput
from environment_store.tui.screens.create import CreateStoreScreen
from environment_store.tui.screens.stores import StoresScreen
from tests.tui.pilot import footer, notifications, rows, run_app, set_input


def _error(app: EnvironmentStoreApp, selector: str) -> str:
    """The inline error a dialog shows under an input; empty when it is hidden."""
    widget = app.screen.query_one(selector, Static)
    return str(widget.content) if widget.display else ""


async def _open_dialog(pilot: Pilot[None]) -> None:
    await pilot.press("a")
    await pilot.pause()


async def _choose(pilot: Pilot[None], button: str) -> None:
    await pilot.click(button)
    await pilot.pause()


def test_a_opens_the_create_dialog_with_its_keys_in_the_footer(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert isinstance(app.screen, CreateStoreScreen)
        assert footer(app) == [("enter", "Create"), ("ctrl+s", "Create"), ("escape", "Cancel")]

    run_app(store, scenario)


def test_a_plain_store_is_created_and_listed(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.press(*"base_conf", "enter")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert rows(app) == [["base_conf", "plain"]]
        assert notifications(app) == ["created store 'base_conf'"]

    run_app(store, scenario)
    assert not store.store_info("base_conf").encrypted


def test_q_is_typeable_in_the_name(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.press("q", "a")
        assert app.is_running
        assert app.screen.query_one("#name", Input).value == "qa"

    run_app(store, scenario)


def test_escape_cancels_without_creating(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.press("x", "escape")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(store, scenario)
    assert store.list_stores() == []


def test_the_cancel_button_cancels(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(store, scenario)


def test_the_name_is_validated_as_you_type(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert _error(app, "#name-error") == ""
        await pilot.press("1")
        assert "invalid store name '1'" in _error(app, "#name-error")
        await pilot.press("backspace", "a", "-", "b")
        assert _error(app, "#name-error") == ""
        await pilot.press("backspace", "backspace", "backspace")
        assert _error(app, "#name-error") == ""

    run_app(store, scenario)


def test_an_existing_name_is_an_inline_error(store: EnvironmentStore) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "base")
        assert _error(app, "#name-error") == "store 'base' exists already"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)

    run_app(store, scenario)


@pytest.mark.parametrize(("typed", "expected"), [("", "enter a store name"), ("Bad", "invalid")])
def test_creating_with_an_invalid_name_keeps_the_dialog(
    store: EnvironmentStore, typed: str, expected: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", typed)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        assert expected in _error(app, "#name-error")

    run_app(store, scenario)
    assert store.list_stores() == []


def test_the_key_fields_appear_for_their_encryption_only(store: EnvironmentStore) -> None:
    def shown(app: EnvironmentStoreApp) -> list[str]:
        ids = ["#generate-fields", "#keyfile-fields", "#passphrase-fields"]
        return [selector for selector in ids if app.screen.query_one(selector).display]

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert shown(app) == []
        await _choose(pilot, "#generate")
        assert shown(app) == ["#generate-fields"]
        await _choose(pilot, "#keyfile")
        assert shown(app) == ["#keyfile-fields"]
        await _choose(pilot, "#passphrase")
        assert shown(app) == ["#passphrase-fields"]
        await _choose(pilot, "#none")
        assert shown(app) == []

    run_app(store, scenario)


def test_the_key_file_inputs_complete_paths(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert isinstance(app.screen.query_one("#generate-path"), PathInput)
        assert isinstance(app.screen.query_one("#key-path"), PathInput)

    run_app(store, scenario)


def test_a_new_key_file_path_is_suggested_from_the_name(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#generate")
        path = app.screen.query_one("#generate-path", PathInput)
        assert path.value == "./app.key"
        await set_input(pilot, "#name", "app2")
        assert path.value == "./app2.key"
        await set_input(pilot, "#generate-path", "./mine.key")
        await set_input(pilot, "#name", "app3")
        assert path.value == "./mine.key"

    run_app(store, scenario)


def test_a_new_key_file_is_generated_with_0600_and_the_reminder_names_it(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#generate")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert rows(app) == [["app", "encrypted (keyfile)"]]
        created, reminder = notifications(app)
        assert created == "created store 'app'"
        assert reminder == (
            "the new key was written to './app.key'; envs does not save it anywhere else: keep "
            "it, or store 'app' cannot be read again"
        )

    run_app(store, scenario)
    key = tmp_path / "app.key"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    store.set("app", "X", "1", key=key)


def test_an_existing_path_for_a_new_key_file_is_refused_inline(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    taken = tmp_path / "app.key"
    taken.write_text("keep me")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#generate")
        assert _error(app, "#generate-error") == (
            "'./app.key' exists already; a key file is never overwritten: choose another path"
        )
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        await set_input(pilot, "#generate-path", "./other.key")
        assert _error(app, "#generate-error") == ""

    run_app(store, scenario)
    assert taken.read_text() == "keep me"
    assert store.list_stores() == []


@pytest.mark.parametrize(
    ("path", "expected"),
    [("", "enter the path of the new key file"), ("~nosuchuser_zz/a.key", "unknown home")],
)
def test_a_missing_or_invalid_new_key_path_is_refused_inline(
    store: EnvironmentStore, path: str, expected: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#generate")
        await set_input(pilot, "#generate-path", path)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        assert expected in _error(app, "#generate-error")

    run_app(store, scenario)
    assert store.list_stores() == []


def test_an_existing_key_file_encrypts_the_store_without_a_reminder(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    key = tmp_path / "given.key"
    generate_key_file(key)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#keyfile")
        await set_input(pilot, "#key-path", "./given.key")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == ["created store 'app'"]

    run_app(store, scenario)
    assert store.store_info("app").key_mode is KeyMode.KEYFILE
    store.set("app", "X", "1", key=key)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", "enter the path of the key file"),
        ("~nosuchuser_zz/a.key", "key file path '~nosuchuser_zz/a.key' names an unknown home"),
    ],
)
def test_a_missing_or_invalid_key_file_path_is_refused_inline(
    store: EnvironmentStore, path: str, expected: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#keyfile")
        await set_input(pilot, "#key-path", path)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        assert _error(app, "#key-error").startswith(expected)
        await set_input(pilot, "#key-path", "a")
        assert _error(app, "#key-error") == ""

    run_app(store, scenario)
    assert store.list_stores() == []


def test_a_file_that_is_no_key_file_is_a_library_error_in_tui_wording(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    (tmp_path / "notes.txt").write_text("not a key\n")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#keyfile")
        await set_input(pilot, "#key-path", "notes.txt")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        [message] = notifications(app)
        assert message.endswith("; create one with envs keygen")

    run_app(store, scenario)
    assert store.list_stores() == []


def test_a_passphrase_typed_twice_encrypts_the_store_with_a_reminder(
    store: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#passphrase")
        await set_input(pilot, "#passphrase-input", "correct horse")
        await set_input(pilot, "#repeat", "correct horse")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == [
            "created store 'app'",
            "envs does not save this passphrase; keep it, or store 'app' cannot be read again",
        ]

    run_app(store, scenario)
    assert store.store_info("app").key_mode is KeyMode.PASSPHRASE
    store.set("app", "X", "1", key=Passphrase(text="correct horse"))


def test_different_passphrases_are_an_inline_error(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#passphrase")
        await set_input(pilot, "#passphrase-input", "one")
        assert _error(app, "#passphrase-error") == ""
        await set_input(pilot, "#repeat", "two")
        assert _error(app, "#passphrase-error") == "the passphrases do not match"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        await set_input(pilot, "#repeat", "one")
        assert _error(app, "#passphrase-error") == ""

    run_app(store, scenario)
    assert store.list_stores() == []


def test_an_empty_passphrase_is_refused_inline(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        await _choose(pilot, "#passphrase")
        await pilot.click("#create")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        assert _error(app, "#passphrase-error") == "enter a passphrase"

    run_app(store, scenario)


def test_a_store_created_elsewhere_meanwhile_is_reported(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        other.create_store("app")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, CreateStoreScreen)
        [message] = notifications(app)
        assert "'app'" in message
        assert "exists" in message

    run_app(store, scenario)


def test_the_create_button_creates(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#name", "app")
        assert isinstance(app.screen.query_one("#create"), Button)
        await pilot.click("#create")
        await pilot.pause()
        assert rows(app) == [["app", "plain"]]

    run_app(store, scenario)
