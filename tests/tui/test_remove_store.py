"""Removing a store in the TUI: only after its exact name is typed, without a key (D55, D21)."""

from textual.pilot import Pilot
from textual.widgets import Button, Input, Label

from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.remove import RemoveStoreScreen
from environment_store.tui.screens.stores import StoresScreen
from tests.tui.pilot import footer, notifications, rows, run_app, set_input


async def _open_dialog(pilot: Pilot[None], *keys: str) -> None:
    await pilot.press(*keys, "d")
    await pilot.pause()


def test_d_opens_a_dialog_that_warns_the_removal_cannot_be_undone(
    store: EnvironmentStore,
) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert isinstance(app.screen, RemoveStoreScreen)
        texts = [str(label.content) for label in app.screen.query(Label)]
        assert texts[0] == (
            "Remove store 'base'? The store and all its variables are deleted. This cannot be "
            "undone."
        )
        assert footer(app) == [("enter", "Remove"), ("escape", "Cancel")]

    run_app(store, scenario)


def test_the_remove_button_works_only_with_the_exact_name(store: EnvironmentStore) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        button = app.screen.query_one("#remove", Button)
        assert button.disabled
        await pilot.press(*"bas")
        assert button.disabled
        await pilot.press("e")
        assert not button.disabled
        await pilot.press("x")
        assert button.disabled

    run_app(store, scenario)


def test_a_mismatched_name_keeps_the_store(store: EnvironmentStore) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#confirm", "Base")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RemoveStoreScreen)
        assert notifications(app) == ["type the store name 'base' exactly to remove it"]

    run_app(store, scenario)
    assert [info.name for info in store.list_stores()] == ["base"]


def test_the_exact_name_removes_the_store_and_refreshes_the_list(store: EnvironmentStore) -> None:
    store.create_store("app")
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot, "down")
        await pilot.press(*"base", "enter")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert rows(app) == [["app", "plain"]]
        assert notifications(app) == ["removed store 'base'"]

    run_app(store, scenario)


def test_an_encrypted_store_is_removed_without_a_key(store: EnvironmentStore) -> None:
    store.create_store("enc", encrypt=True, key=Passphrase(text="lost"))

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await set_input(pilot, "#confirm", "enc")
        await pilot.click("#remove")
        await pilot.pause()
        assert rows(app) == []

    run_app(store, scenario)
    assert store.list_stores() == []


def test_q_is_typeable_in_the_name(store: EnvironmentStore) -> None:
    store.create_store("q1")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.press("q", "1")
        assert app.is_running
        assert app.screen.query_one("#confirm", Input).value == "q1"

    run_app(store, scenario)


def test_escape_cancels_the_removal(store: EnvironmentStore) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.press(*"base", "escape")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert rows(app) == [["base", "plain"]]

    run_app(store, scenario)


def test_the_cancel_button_cancels_the_removal(store: EnvironmentStore) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(store, scenario)
    assert [info.name for info in store.list_stores()] == ["base"]


def test_d_without_stores_does_nothing(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        assert isinstance(app.screen, StoresScreen)

    run_app(store, scenario)


def test_a_store_removed_elsewhere_meanwhile_is_reported_and_the_list_refreshed(
    store: EnvironmentStore, other: EnvironmentStore
) -> None:
    store.create_store("base")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_dialog(pilot)
        other.delete_store("base")
        await pilot.press(*"base", "enter")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        [message] = notifications(app)
        assert message.startswith("store 'base' not found")
        assert rows(app) == []

    run_app(store, scenario)
