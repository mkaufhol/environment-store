"""The stores screen and unlocking (PD 29): list, open plain, project key, typed key, wrong key."""

from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, Static

from environment_store.core.models import StoreInfo
from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.stores import StoresScreen
from environment_store.tui.screens.unlock import UnlockScreen, describe_encryption
from environment_store.tui.screens.variables import MASK, VariablesScreen
from tests.tui.pilot import notifications, rows, run_app, set_input


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "a.key"
    generate_key_file(path)
    return path


@pytest.fixture
def encrypted(store: EnvironmentStore, key: Path) -> EnvironmentStore:
    """Store `a` encrypted with `key`, holding SECRET=hidden-value."""
    store.create_store("a", encrypt=True, key=key)
    store.set("a", "SECRET", "hidden-value", key=key)
    return store


@pytest.fixture
def passphrase_store(store: EnvironmentStore) -> EnvironmentStore:
    """Store `p` with the passphrase `correct horse`, holding SECRET=hidden-value."""
    secret = Passphrase(text="correct horse")
    store.create_store("p", encrypt=True, key=secret)
    store.set("p", "SECRET", "hidden-value", key=secret)
    return store


async def _open_first(pilot: Pilot[None]) -> None:
    await pilot.press("enter")
    await pilot.pause()


def test_stores_screen_lists_every_store_with_its_encryption(
    store: EnvironmentStore, key: Path
) -> None:
    store.create_store("plain_one")
    store.create_store("with_key", encrypt=True, key=key)
    store.create_store("with_pass", encrypt=True, key=Passphrase(text="pw"))

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        assert isinstance(app.screen, StoresScreen)
        assert rows(app) == [
            ["plain_one", "plain"],
            ["with_key", "encrypted (keyfile)"],
            ["with_pass", "encrypted (passphrase)"],
        ]

    run_app(store, scenario)


def test_an_empty_backend_shows_how_to_create_a_store(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        hint = app.screen.query_one("#empty", Static)
        assert hint.display
        assert str(hint.content) == "No stores yet. Create one with envs create-store NAME"

    run_app(store, scenario)


def test_the_empty_hint_disappears_when_a_store_exists(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        other.create_store("new")
        await pilot.press("r")
        assert not app.screen.query_one("#empty", Static).display

    run_app(store, scenario)


def test_a_failing_listing_shows_no_empty_hint(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        store.close()
        await pilot.press("r")
        assert not app.screen.query_one("#empty", Static).display

    run_app(store, scenario)


def test_stores_screen_reload_shows_a_store_created_elsewhere(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        assert rows(app) == []
        other.create_store("new")
        await pilot.press("r")
        assert rows(app) == [["new", "plain"]]

    run_app(store, scenario)


def test_stores_screen_reports_a_failing_listing_as_a_notification(
    store: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        store.close()
        await pilot.press("r")
        assert rows(app) == []
        assert notifications(app) == ["this EnvironmentStore is closed"]

    run_app(store, scenario)


def test_q_quits_the_app(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running

    run_app(store, scenario)


def test_enter_opens_a_plain_store_with_masked_values(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set_many("a", {"HOST": "localhost", "PORT": "5432"})

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["HOST", MASK], ["PORT", MASK]]

    run_app(store, scenario)


def test_opening_a_store_deleted_elsewhere_notifies_and_stays_on_the_list(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    store.create_store("a")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        other.delete_store("a")
        await _open_first(pilot)
        assert isinstance(app.screen, StoresScreen)
        [message] = notifications(app)
        assert message.startswith("store 'a' not found")

    run_app(store, scenario)


def test_encrypted_store_opens_with_the_project_key_without_asking(
    encrypted: EnvironmentStore, key: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["SECRET", MASK]]

    run_app(encrypted, scenario, key_paths={"a": key})


def test_wrong_project_key_notifies_and_asks_for_a_key(
    encrypted: EnvironmentStore, tmp_path: Path
) -> None:
    wrong = tmp_path / "wrong.key"
    generate_key_file(wrong)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith(
            f"unlocking with the key file '{wrong}' from the project file failed: "
            "cannot decrypt store 'a'"
        )
        assert "hidden-value" not in message

    run_app(encrypted, scenario, key_paths={"a": wrong})


def test_missing_project_key_file_names_it_and_asks_for_a_key(
    encrypted: EnvironmentStore, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.key"

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith(
            f"unlocking with the key file '{missing}' from the project file failed: "
        )

    run_app(encrypted, scenario, key_paths={"a": missing})


def test_plaintext_store_with_a_project_key_notifies_and_stays_on_the_list(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("a")
    project = tmp_path / ".envstore.toml"
    app = EnvironmentStoreApp(
        store, key_paths={"a": tmp_path / "missing.key"}, project_file=project
    )

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == [
            f"[keys] in '{project}' names a key for store 'a', which is not encrypted: "
            "remove the entry"
        ]

    run_app(store, scenario, app=app)


def test_unlock_with_an_unknown_home_directory_notifies_and_stays_locked(
    encrypted: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", "~nosuchuser_zz/a.key")
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith("unlocking with the key file '~nosuchuser_zz/a.key' failed: ")

    run_app(encrypted, scenario)


def test_encrypted_store_without_project_key_asks_for_a_key(encrypted: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == []

    run_app(encrypted, scenario)


def test_unlock_with_a_typed_key_file_path_opens_the_store(
    encrypted: EnvironmentStore, key: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await pilot.press(*str(key))
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["SECRET", MASK]]

    run_app(encrypted, scenario)


def test_a_wrong_key_file_names_the_key_file(encrypted: EnvironmentStore, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.key"
    generate_key_file(wrong)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", str(wrong))
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == [
            f"unlocking with the key file '{wrong}' failed: cannot decrypt store 'a': wrong key "
            "or passphrase, or the stored data was modified"
        ]

    run_app(encrypted, scenario)


def test_unlock_with_a_passphrase_opens_the_store(passphrase_store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#passphrase", "correct horse")
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["SECRET", MASK]]

    run_app(passphrase_store, scenario)


def test_passphrase_input_hides_what_is_typed(passphrase_store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert app.screen.query_one("#passphrase", Input).password

    run_app(passphrase_store, scenario)


def test_wrong_passphrase_notifies_and_the_store_stays_locked(
    passphrase_store: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#passphrase", "wrong guess")
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message == (
            "unlocking with the typed passphrase failed: cannot decrypt store 'p': wrong key or "
            "passphrase, or the stored data was modified"
        )
        assert "wrong guess" not in message
        assert "hidden-value" not in message
        assert app.screen.query_one("#passphrase", Input).value == ""

    run_app(passphrase_store, scenario)


def test_unreadable_key_file_notifies_with_the_path(
    encrypted: EnvironmentStore, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.key"

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", str(missing))
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith(f"unlocking with the key file '{missing}' failed: cannot read")

    run_app(encrypted, scenario)


@pytest.mark.parametrize(("path", "passphrase"), [("", ""), ("a.key", "pw")])
def test_unlock_needs_exactly_one_of_path_and_passphrase(
    passphrase_store: EnvironmentStore, path: str, passphrase: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", path)
        await set_input(pilot, "#passphrase", passphrase)
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == ["enter either a key or passphrase file, or the passphrase"]

    run_app(passphrase_store, scenario)


@pytest.mark.parametrize("cancel", ["escape", "#cancel"])
def test_cancelled_unlock_returns_to_the_stores(
    passphrase_store: EnvironmentStore, cancel: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        if cancel.startswith("#"):
            await pilot.click(cancel)
        else:
            await pilot.press(cancel)
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(passphrase_store, scenario)


def test_unlock_shows_an_unknown_key_mode(store: EnvironmentStore) -> None:
    info = store.create_store("a", encrypt=True, key=Passphrase(text="pw"))
    unknown = StoreInfo(
        name="a",
        encrypted=True,
        key_mode=None,
        revision=info.revision,
        created_at=info.created_at,
        updated_at=info.updated_at,
    )

    assert describe_encryption(unknown) == "encrypted (unknown)"


def test_escape_on_the_variables_screen_returns_to_the_stores(store: EnvironmentStore) -> None:
    store.create_store("a")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(store, scenario)


def test_invalid_key_file_notifies_with_the_tui_hint(
    encrypted: EnvironmentStore, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.key"
    bad.write_text("garbage\n", encoding="utf-8")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", str(bad))
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message.startswith("not a valid key file: ")
        assert message.endswith("; create one with envs keygen")
        assert "generate_key" not in message

    run_app(encrypted, scenario)
