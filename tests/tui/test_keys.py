"""Keys of the TUI (D46): no command palette, footers list the keys that work, q quits."""

import pytest
from textual.command import CommandPalette
from textual.pilot import Pilot

from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.confirm import ConfirmScreen
from environment_store.tui.screens.edit import EditVariableScreen
from environment_store.tui.screens.stores import StoresScreen
from environment_store.tui.screens.unlock import UnlockScreen
from environment_store.tui.screens.variables import VariablesScreen
from tests.tui.pilot import footer, run_app

_STORES_KEYS = [("enter", "Open"), ("r", "Reload"), ("q", "Quit")]
_VARIABLES_KEYS = [
    ("enter", "Edit"),
    ("v", "Show / hide values"),
    ("a", "Add"),
    ("e", "Edit"),
    ("d", "Delete"),
    ("r", "Reload"),
    ("escape", "Back"),
    ("q", "Quit"),
]


@pytest.fixture
def plain(store: EnvironmentStore) -> EnvironmentStore:
    """Plain store `a` with HOST=localhost."""
    store.create_store("a")
    store.set("a", "HOST", "localhost")
    return store


async def _press(pilot: Pilot[None], *keys: str) -> None:
    await pilot.press(*keys)
    await pilot.pause()


def test_the_command_palette_is_disabled(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "ctrl+p")
        assert isinstance(app.screen, StoresScreen)
        assert not any(isinstance(screen, CommandPalette) for screen in app.screen_stack)

    app = run_app(store, scenario)

    assert not app.ENABLE_COMMAND_PALETTE


def test_the_stores_footer_lists_enter_to_open(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        assert footer(app) == _STORES_KEYS

    run_app(plain, scenario)


def test_the_variables_footer_lists_enter_to_edit(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "enter")
        assert isinstance(app.screen, VariablesScreen)
        assert footer(app) == _VARIABLES_KEYS

    run_app(plain, scenario)


def test_the_unlock_dialog_shows_its_own_keys(store: EnvironmentStore) -> None:
    store.create_store("p", encrypt=True, key=Passphrase(text="pw"))

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "enter")
        assert isinstance(app.screen, UnlockScreen)
        assert footer(app) == [("enter", "Unlock"), ("escape", "Cancel")]

    run_app(store, scenario)


@pytest.mark.parametrize("key", ["a", "e"])
def test_the_edit_dialog_shows_its_own_keys(plain: EnvironmentStore, key: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "enter", key)
        assert isinstance(app.screen, EditVariableScreen)
        assert footer(app) == [("ctrl+s", "Save"), ("escape", "Cancel")]

    run_app(plain, scenario)


def test_the_confirm_dialog_shows_its_own_keys(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "enter", "d")
        assert isinstance(app.screen, ConfirmScreen)
        assert footer(app) == [("y", "Yes"), ("n", "No"), ("escape", "Cancel")]

    run_app(plain, scenario)


def test_q_quits_the_app_from_the_variables_screen(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _press(pilot, "enter")
        assert isinstance(app.screen, VariablesScreen)
        await _press(pilot, "q")
        assert not app.is_running

    run_app(plain, scenario)
