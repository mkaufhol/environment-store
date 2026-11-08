"""Exporting from the TUI (D56): stores in order, options, path, keys, mode 0600, D52 order."""

import json
import stat
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Checkbox, RadioSet, SelectionList, Static

from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.paths import PathInput
from environment_store.tui.screens.confirm import ConfirmScreen
from environment_store.tui.screens.export import (
    ExportOptionsScreen,
    ExportPathScreen,
    ExportStoresScreen,
)
from environment_store.tui.screens.stores import StoresScreen
from tests.tui.export_steps import export_to, to_options, to_path, toggle
from tests.tui.pilot import footer, notifications, run_app, set_input


@pytest.fixture
def arranged(store: EnvironmentStore) -> EnvironmentStore:
    """Plaintext stores `app` and `base` sharing HOST."""
    store.create_store("app")
    store.set_many("app", {"HOST": "app-host", "A_ONLY": "a"})
    store.create_store("base")
    store.set_many("base", {"HOST": "base-host", "B_ONLY": "b"})
    return store


def _prompts(app: EnvironmentStoreApp) -> list[str]:
    choice = app.screen.query_one(SelectionList)
    return [str(choice.get_option_at_index(index).prompt) for index in range(choice.option_count)]


def _pressed_format(app: EnvironmentStoreApp) -> str | None:
    pressed = app.screen.query_one(RadioSet).pressed_button
    return None if pressed is None else pressed.id


def test_x_opens_step_one_with_its_keys_in_the_footer(arranged: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ExportStoresScreen)
        assert footer(app) == [("space", "Choose"), ("ctrl+s", "Next"), ("escape", "Cancel")]
        assert _prompts(app) == ["    app  (plain)", "    base  (plain)"]

    run_app(arranged, scenario)


def test_choosing_stores_numbers_them_in_order_and_unchoosing_renumbers(
    arranged: EnvironmentStore,
) -> None:
    arranged.create_store("cfg")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("down", "down", "space", "up", "space", "up", "space")
        await pilot.pause()
        assert isinstance(app.screen, ExportStoresScreen)
        assert app.screen.order == ["cfg", "base", "app"]
        assert _prompts(app) == [" 3  app  (plain)", " 2  base  (plain)", " 1  cfg  (plain)"]
        await pilot.press("down", "down", "space")
        await pilot.pause()
        assert app.screen.order == ["base", "app"]
        assert _prompts(app) == [" 2  app  (plain)", " 1  base  (plain)", "    cfg  (plain)"]

    run_app(arranged, scenario)


def test_next_without_a_store_is_refused(arranged: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        await pilot.click("#next")
        await pilot.pause()
        assert isinstance(app.screen, ExportStoresScreen)
        assert notifications(app) == ["choose at least one store to export"]

    run_app(arranged, scenario)


def test_x_without_stores_says_so(store: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == ["there are no stores to export"]

    run_app(store, scenario)


@pytest.mark.parametrize(("ordered_overwrite", "first_wins"), [(True, False), (False, True)])
def test_step_two_shows_the_options_with_the_configured_merge_order(
    arranged: EnvironmentStore, *, ordered_overwrite: bool, first_wins: bool
) -> None:
    tui = EnvironmentStoreApp(arranged, key_paths={}, ordered_overwrite=ordered_overwrite)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await to_options(pilot, "base")
        assert isinstance(app.screen, ExportOptionsScreen)
        assert _pressed_format(app) == "fmt-dotenv"
        assert not app.screen.query_one("#nested", Checkbox).value
        assert app.screen.query_one("#first-wins", Checkbox).value is first_wins
        assert footer(app)[-2:] == [("ctrl+s", "Next"), ("escape", "Cancel")]

    run_app(arranged, scenario, app=tui)


def test_step_three_preselects_the_format_from_the_extension(arranged: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await to_path(pilot, "base")
        assert isinstance(app.screen, ExportPathScreen)
        assert isinstance(app.screen.query_one("#path"), PathInput)
        assert footer(app)[:2] == [("enter", "Export"), ("tab", "Complete path")]
        assert _pressed_format(app) == "fmt-dotenv"
        await set_input(pilot, "#path", "out.json")
        assert _pressed_format(app) == "fmt-json"
        await pilot.click("#fmt-toml")
        await set_input(pilot, "#path", "out.jsonx")
        assert _pressed_format(app) == "fmt-toml"
        await set_input(pilot, "#path", "settings.toml")
        assert _pressed_format(app) == "fmt-toml"
        await set_input(pilot, "#path", ".env.local")
        assert _pressed_format(app) == "fmt-dotenv"

    run_app(arranged, scenario)


def test_export_writes_the_stores_in_load_order_with_mode_0600(
    arranged: EnvironmentStore, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.json", "base", "app")
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == ["exported to 'out.json'"]

    run_app(arranged, scenario)
    out = tmp_path / "out.json"
    assert list(json.loads(out.read_text()).items()) == [
        ("B_ONLY", "b"),
        ("HOST", "app-host"),
        ("A_ONLY", "a"),
    ]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_nested_and_first_wins_change_the_output(
    arranged: EnvironmentStore, tmp_path: Path
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await to_options(pilot, "base", "app")
        await pilot.click("#first-wins")
        await pilot.click("#fmt-toml")
        await pilot.click("#next")
        await pilot.pause()
        await set_input(pilot, "#path", "out.txt")
        await pilot.click("#export")
        await pilot.pause()

    run_app(arranged, scenario)
    assert 'HOST = "base-host"' in (tmp_path / "out.txt").read_text()


def test_nested_dotenv_prefixes_the_store_names(arranged: EnvironmentStore, tmp_path: Path) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await to_options(pilot, "app")
        await pilot.click("#nested")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await set_input(pilot, "#path", "out.env")
        await pilot.press("ctrl+s")
        await pilot.pause()

    run_app(arranged, scenario)
    assert (tmp_path / "out.env").read_text() == "APP__A_ONLY=a\nAPP__HOST=app-host\n"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("", "enter the path of the output file"),
        ("~nosuchuser_zz/out.env", "unknown home directory"),
        (".", "'.' is a directory: enter a file path"),
    ],
)
def test_an_unusable_path_is_an_inline_error(
    arranged: EnvironmentStore, typed: str, expected: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, typed, "base")
        assert isinstance(app.screen, ExportPathScreen)
        error = app.screen.query_one("#path-error", Static)
        assert error.display
        assert expected in str(error.content)
        await set_input(pilot, "#path", "x")
        assert not error.display

    run_app(arranged, scenario)


def test_an_existing_file_is_kept_when_replacing_is_declined(
    arranged: EnvironmentStore, tmp_path: Path
) -> None:
    out = tmp_path / "out.env"
    out.write_text("old")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.env", "base")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, ExportPathScreen)

    run_app(arranged, scenario)
    assert out.read_text() == "old"


def test_an_existing_file_is_replaced_after_confirming(
    arranged: EnvironmentStore, tmp_path: Path
) -> None:
    out = tmp_path / "out.env"
    out.write_text("old")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.env", "base")
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)
        assert notifications(app) == [f"exported to '{out.relative_to(tmp_path)}'"]

    run_app(arranged, scenario)
    assert out.read_text() == "B_ONLY=b\nHOST=base-host\n"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_a_value_dotenv_cannot_hold_is_reported_in_tui_wording(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("base")
    store.set("base", "URL", "${HOME}")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await export_to(pilot, "out.env", "base")
        [message] = notifications(app)
        assert message.endswith("; choose the JSON or TOML format")

    run_app(store, scenario)
    assert not (tmp_path / "out.env").exists()


@pytest.mark.parametrize("step", [1, 2, 3])
def test_escape_at_any_step_cancels_the_export(arranged: EnvironmentStore, step: int) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        await toggle(pilot, "base")
        for _ in range(step - 1):
            await pilot.press("ctrl+s")
            await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(arranged, scenario)


@pytest.mark.parametrize("button", ["#cancel"])
@pytest.mark.parametrize("step", [1, 2, 3])
def test_the_cancel_button_cancels_at_any_step(
    arranged: EnvironmentStore, step: int, button: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await pilot.press("x")
        await pilot.pause()
        await toggle(pilot, "base")
        for _ in range(step - 1):
            await pilot.click("#next")
            await pilot.pause()
        await pilot.click(button)
        await pilot.pause()
        assert isinstance(app.screen, StoresScreen)

    run_app(arranged, scenario)
