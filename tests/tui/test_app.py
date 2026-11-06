"""`run_tui` and the `tui` package guard (spec §6.14, PD 29)."""

import importlib
import sys
from pathlib import Path

import pytest

from environment_store.core.errors import MissingExtraError
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp, run_tui


def test_run_tui_runs_the_app_on_the_store_in_the_terminal(
    store: EnvironmentStore, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ran: list[EnvironmentStoreApp] = []

    def fake_run(app: EnvironmentStoreApp) -> None:
        # The terminal is the boundary: record the app instead of taking over the terminal.
        ran.append(app)

    monkeypatch.setattr(EnvironmentStoreApp, "run", fake_run)
    store.create_store("a")

    run_tui(store, key_paths={"a": tmp_path / "a.key"})

    [app] = ran
    assert isinstance(app, EnvironmentStoreApp)


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
