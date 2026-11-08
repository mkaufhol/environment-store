"""`run_tui` and the `tui` package guard (spec §6.14, PD 29)."""

import importlib
import sys
from pathlib import Path

import pytest
from textual.app import AutopilotCallbackType
from textual.pilot import Pilot
from textual.widgets import Checkbox, SelectionList

from environment_store.core.errors import MissingExtraError
from environment_store.core.models import StoreInfo
from environment_store.library.keys import generate_key_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp, run_tui
from environment_store.tui.screens.variables import VariablesScreen


def _run_headless(monkeypatch: pytest.MonkeyPatch, auto_pilot: AutopilotCallbackType) -> None:
    """Run the app of `run_tui` headless, driven by `auto_pilot`: the terminal is the boundary."""
    run = EnvironmentStoreApp.run

    def headless(app: EnvironmentStoreApp) -> None:
        run(app, headless=True, size=(120, 40), auto_pilot=auto_pilot)

    monkeypatch.setattr(EnvironmentStoreApp, "run", headless)


def test_run_tui_runs_the_app_on_the_store_with_the_project_keys(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = tmp_path / "a.key"
    generate_key_file(key)
    store.create_store("a", encrypt=True, key=key)
    store.set("a", "SECRET", "hidden-value", key=key)
    shown: list[object] = []

    async def auto_pilot(pilot: Pilot[object]) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        shown.append(pilot.app.screen)
        pilot.app.exit()

    _run_headless(monkeypatch, auto_pilot)

    run_tui(store, key_paths={"a": key})

    [screen] = shown
    assert isinstance(screen, VariablesScreen)
    assert dict(screen.opened.variables) == {"SECRET": "hidden-value"}


def test_run_tui_names_the_project_file_in_its_errors(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store.create_store("a")
    project = tmp_path / ".envstore.toml"
    messages: list[str] = []

    async def auto_pilot(pilot: Pilot[object]) -> None:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        messages.extend(notification.message for notification in pilot.app._notifications)
        pilot.app.exit()

    _run_headless(monkeypatch, auto_pilot)

    run_tui(store, key_paths={"a": tmp_path / "a.key"}, project_file=project)

    [message] = messages
    assert message.startswith(f"[keys] in '{project}'")


def test_run_tui_gives_the_export_dialog_the_configured_merge_order(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.create_store("a")
    first_wins: list[bool] = []

    async def auto_pilot(pilot: Pilot[object]) -> None:
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        pilot.app.screen.query_one(SelectionList).toggle("a")
        await pilot.press("ctrl+s")
        await pilot.pause()
        first_wins.append(pilot.app.screen.query_one("#first-wins", Checkbox).value)
        pilot.app.exit()

    _run_headless(monkeypatch, auto_pilot)

    run_tui(store, key_paths={}, ordered_overwrite=False)

    assert first_wins == [True]


def test_run_tui_after_a_crash_exits_non_zero_without_locals_in_the_traceback(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "hidden" + "-value"  # built at run time: the traceback shows source lines

    def crash() -> list[StoreInfo]:
        value = secret
        message = f"unexpected failure ({len(value)})"
        raise RuntimeError(message)

    monkeypatch.setattr(store, "list_stores", crash)

    async def auto_pilot(pilot: Pilot[object]) -> None:
        await pilot.pause()

    _run_headless(monkeypatch, auto_pilot)

    with pytest.raises(SystemExit) as raised:
        run_tui(store, key_paths={})

    assert raised.value.code == 1
    printed = capsys.readouterr()
    assert "unexpected failure (12)" in printed.err
    assert "hidden-value" not in printed.out + printed.err


def test_the_app_is_titled_environment_store(store: EnvironmentStore) -> None:
    assert EnvironmentStoreApp(store, key_paths={}).title == "Environment Store"


def test_importing_the_tui_without_textual_raises_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "textual", None)
    for module in [name for name in sys.modules if name.startswith("environment_store.tui")]:
        monkeypatch.delitem(sys.modules, module)

    with pytest.raises(MissingExtraError) as raised:
        importlib.import_module("environment_store.tui")

    assert raised.value.extra == "tui"


def test_the_package_resolves_its_api_from_the_app_module() -> None:
    import environment_store.tui as package  # noqa: PLC0415 - the package object itself

    assert package.run_tui is run_tui
    assert package.EnvironmentStoreApp is EnvironmentStoreApp


def test_the_package_has_no_other_attributes() -> None:
    import environment_store.tui as package  # noqa: PLC0415 - the package object itself

    with pytest.raises(AttributeError, match="no attribute 'missing'"):
        _ = package.missing
