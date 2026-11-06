"""The variables screen (PD 29): masked values, add / edit multi-line / delete, reload, D7."""

from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, TextArea

from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.errors import BackendError
from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore, open_configured_adapter
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.confirm import ConfirmScreen
from environment_store.tui.screens.edit import EditVariableScreen
from environment_store.tui.screens.variables import MASK, VariablesScreen, shown_value
from tests.support.cli import hooked, raising
from tests.tui.pilot import notifications, rows, run_app, set_input, set_text

_PASSPHRASE = Passphrase(text="pw")


@pytest.fixture
def plain(store: EnvironmentStore) -> EnvironmentStore:
    """Store `a` with HOST=localhost and PORT=5432."""
    store.create_store("a")
    store.set_many("a", {"HOST": "localhost", "PORT": "5432"})
    return store


@pytest.fixture
def locked(store: EnvironmentStore, tmp_path: Path) -> tuple[EnvironmentStore, Path]:
    """Store `a` with a passphrase (in a project key file), holding TOKEN=t0ken."""
    store.create_store("a", encrypt=True, key=_PASSPHRASE)
    store.set("a", "TOKEN", "t0ken", key=_PASSPHRASE)
    path = tmp_path / "p.txt"
    path.write_text("pw\n", encoding="utf-8")
    return store, path


async def _open(pilot: Pilot[None]) -> VariablesScreen:
    await pilot.press("enter")
    await pilot.pause()
    screen = pilot.app.screen
    assert isinstance(screen, VariablesScreen)
    return screen


async def _save(pilot: Pilot[None]) -> None:
    await pilot.press("ctrl+s")
    await pilot.pause()


def test_v_shows_and_hides_the_values(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("v")
        assert rows(app) == [["HOST", "localhost"], ["PORT", "5432"]]
        await pilot.press("v")
        assert rows(app) == [["HOST", MASK], ["PORT", MASK]]

    run_app(plain, scenario)


def test_values_are_shown_as_text_not_markup(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set("a", "STYLE", "[bold]x[/bold]")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("v")
        assert rows(app) == [["STYLE", "[bold]x[/bold]"]]

    run_app(store, scenario)


@pytest.mark.parametrize(
    ("value", "shown"),
    [("plain", "plain"), ("two\nlines", '"two\\nlines"'), ("tab\there", '"tab\\there"')],
)
def test_shown_value_keeps_one_line_per_variable(value: str, shown: str) -> None:
    assert shown_value(value) == shown


def test_add_creates_a_variable_with_a_multi_line_value(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, EditVariableScreen)
        await pilot.press(*"CERT", "enter")
        await pilot.press(*"line1", "enter", *"line2")
        await _save(pilot)
        assert isinstance(app.screen, VariablesScreen)
        assert ["CERT", MASK] in rows(app)

    run_app(plain, scenario)

    assert plain.get("a", "CERT") == "line1\nline2"


def test_add_to_an_encrypted_store_uses_its_key(
    locked: tuple[EnvironmentStore, Path],
) -> None:
    store, path = locked

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a")
        await set_input(pilot, "#name", "NEW")
        await set_text(pilot, "#value", "secret-value")
        await pilot.click("#save")
        await pilot.pause()
        assert rows(app) == [["NEW", MASK], ["TOKEN", MASK]]

    app = run_app(store, scenario, key_paths={"a": path})

    assert store.get("a", "NEW", key=_PASSPHRASE) == "secret-value"
    assert all("secret-value" not in message for message in notifications(app))


def test_add_an_existing_name_keeps_the_dialog_and_writes_nothing(
    plain: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a")
        await set_input(pilot, "#name", "HOST")
        await set_text(pilot, "#value", "other-value")
        await _save(pilot)
        assert isinstance(app.screen, EditVariableScreen)
        [message] = notifications(app)
        assert "HOST" in message
        assert "other-value" not in message

    run_app(plain, scenario)

    assert plain.get("a", "HOST") == "localhost"


def test_add_an_invalid_name_keeps_the_dialog(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a")
        await set_input(pilot, "#name", "1 bad")
        await _save(pilot)
        assert isinstance(app.screen, EditVariableScreen)
        assert len(notifications(app)) == 1

    run_app(plain, scenario)

    assert plain.variables("a") == {"HOST": "localhost", "PORT": "5432"}


@pytest.mark.parametrize("cancel", ["escape", "#cancel"])
def test_cancelled_add_writes_nothing(plain: EnvironmentStore, cancel: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a")
        await set_input(pilot, "#name", "NEW")
        if cancel.startswith("#"):
            await pilot.click(cancel)
        else:
            await pilot.press(cancel)
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)

    run_app(plain, scenario)

    assert plain.variables("a") == {"HOST": "localhost", "PORT": "5432"}


@pytest.mark.parametrize("key", ["e", "enter"])
def test_edit_replaces_the_value_of_the_selected_variable(
    plain: EnvironmentStore, key: str
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("down", key)
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, EditVariableScreen)
        assert dialog.query_one("#name", Input).disabled
        assert dialog.query_one("#value", TextArea).text == "5432"
        await set_text(pilot, "#value", "1\n2\n")
        await _save(pilot)
        assert rows(app) == [["HOST", MASK], ["PORT", MASK]]

    run_app(plain, scenario)

    assert plain.get("a", "PORT") == "1\n2\n"


def test_cancelled_edit_writes_nothing(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("e")
        await set_text(pilot, "#value", "changed")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)

    run_app(plain, scenario)

    assert plain.get("a", "HOST") == "localhost"


def test_enter_in_the_name_input_moves_to_the_value(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("a", "X", "enter")
        await pilot.pause()
        assert app.focused is app.screen.query_one("#value", TextArea)

    run_app(plain, scenario)


def test_delete_after_yes_removes_the_selected_variable(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        assert rows(app) == [["PORT", MASK]]

    run_app(plain, scenario)

    assert plain.variables("a") == {"PORT": "5432"}


@pytest.mark.parametrize("answer", ["n", "escape", "#no"])
def test_delete_without_yes_keeps_the_variable(plain: EnvironmentStore, answer: str) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("d")
        await pilot.pause()
        if answer.startswith("#"):
            await pilot.click(answer)
        else:
            await pilot.press(answer)
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)

    run_app(plain, scenario)

    assert plain.variables("a") == {"HOST": "localhost", "PORT": "5432"}


def test_delete_yes_button_removes_the_variable(plain: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#yes")
        await pilot.pause()

    run_app(plain, scenario)

    assert plain.variables("a") == {"PORT": "5432"}


@pytest.mark.parametrize("key", ["e", "d"])
def test_edit_and_delete_do_nothing_in_an_empty_store(store: EnvironmentStore, key: str) -> None:
    store.create_store("a")

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        await pilot.press(key)
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)

    run_app(store, scenario)


def test_reload_shows_a_change_made_elsewhere(
    plain: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        other.set("a", "NEW", "1")
        await pilot.press("r")
        await pilot.pause()
        assert rows(app) == [["HOST", MASK], ["NEW", MASK], ["PORT", MASK]]

    run_app(plain, scenario)


def test_reload_of_a_store_deleted_elsewhere_notifies(
    plain: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        other.delete_store("a")
        await pilot.press("r")
        await pilot.pause()
        [message] = notifications(app)
        assert message.startswith("store 'a' not found")

    run_app(plain, scenario)


def test_the_cursor_stays_on_the_selected_variable_after_a_reload(
    plain: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        screen = await _open(pilot)
        await pilot.press("down", "r")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, EditVariableScreen)
        assert app.screen.query_one("#value", TextArea).text == "5432"
        assert screen.opened.name == "a"

    run_app(plain, scenario)


def _conflicting_add(
    plain: EnvironmentStore, other: EnvironmentStore, answer: str
) -> list[list[str]]:
    shown: list[list[str]] = []

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        other.set("a", "OTHER", "2")
        await pilot.press("a")
        await set_input(pilot, "#name", "MINE")
        await set_text(pilot, "#value", "mine-value")
        await _save(pilot)
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press(answer)
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)
        shown.extend(rows(app))

    run_app(plain, scenario)
    return shown


def test_a_conflicting_write_writes_nothing_and_reloads_after_yes(
    plain: EnvironmentStore, other: EnvironmentStore
) -> None:
    shown = _conflicting_add(plain, other, "y")

    assert plain.variables("a") == {"HOST": "localhost", "OTHER": "2", "PORT": "5432"}
    assert shown == [["HOST", MASK], ["OTHER", MASK], ["PORT", MASK]]


def test_a_conflicting_write_without_reload_keeps_the_shown_state(
    plain: EnvironmentStore, other: EnvironmentStore
) -> None:
    shown = _conflicting_add(plain, other, "n")

    assert plain.variables("a") == {"HOST": "localhost", "OTHER": "2", "PORT": "5432"}
    assert shown == [["HOST", MASK], ["PORT", MASK]]


def test_a_failing_write_notifies_with_the_error_only(
    plain: EnvironmentStore, other: EnvironmentStore
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open(pilot)
        other.delete_store("a")
        await pilot.press("e")
        await set_text(pilot, "#value", "never-shown")
        await _save(pilot)
        assert isinstance(app.screen, VariablesScreen)
        [message] = notifications(app)
        assert message.startswith("store 'a' not found")

    run_app(plain, scenario)


def test_a_backend_failure_notifies_with_its_message_as_written(
    plain: EnvironmentStore, connection: str
) -> None:
    error = BackendError("see [keys] in the project file")

    def opener(url: str, setup: SetupMode) -> Adapter:
        adapter = open_configured_adapter(url, setup)
        return hooked(adapter, before={"write_store": raising(error)})

    with EnvironmentStore(connection, opener=opener) as store:

        async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
            await _open(pilot)
            await pilot.press("e")
            await _save(pilot)
            assert notifications(app) == ["see [keys] in the project file"]

        run_app(store, scenario)
