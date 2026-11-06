"""`envs tui`: settings like every command, terminal only, the `tui` extra (spec §6.14, PD 31)."""

import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

import environment_store.tui
from environment_store.library.store import EnvironmentStore
from tests.support.cli import CliHarness, assert_exit

_TUI_PACKAGE = "environment_store.tui"


class FakeRunTui:
    """Records the calls of `run_tui` instead of starting the TUI."""

    calls: list[tuple[EnvironmentStore, dict[str, Path]]]
    project_files: list[Path | None]

    def __init__(self) -> None:
        self.calls = []
        self.project_files = []

    def __call__(
        self,
        store: EnvironmentStore,
        *,
        key_paths: Mapping[str, Path],
        project_file: Path | None = None,
    ) -> None:
        assert not store.closed
        self.calls.append((store, dict(key_paths)))
        self.project_files.append(project_file)


@pytest.fixture
def run_tui(monkeypatch: pytest.MonkeyPatch) -> FakeRunTui:
    fake = FakeRunTui()
    monkeypatch.setattr(environment_store.tui, "run_tui", fake)
    return fake


def test_tui_on_a_terminal_runs_the_tui_on_the_configured_store(
    cli_json: CliHarness, run_tui: FakeRunTui
) -> None:
    result = cli_json.invoke("tui", stdin_tty=True, stdout_tty=True)

    assert_exit(result, 0)
    [(store, key_paths)] = run_tui.calls
    assert isinstance(store, EnvironmentStore)
    assert key_paths == {}


def test_tui_closes_the_store_when_the_tui_ends(cli_json: CliHarness, run_tui: FakeRunTui) -> None:
    cli_json.invoke("tui", stdin_tty=True, stdout_tty=True)

    [(store, _)] = run_tui.calls
    assert store.closed


def test_tui_passes_the_project_file_keys(cli_json: CliHarness, run_tui: FakeRunTui) -> None:
    project = cli_json.project_file("[keys]\na = 'a.key'\n")

    result = cli_json.invoke("tui", stdin_tty=True, stdout_tty=True)

    assert_exit(result, 0)
    [(_, key_paths)] = run_tui.calls
    assert key_paths == {"a": cli_json.root / "a.key"}
    assert run_tui.project_files == [project]


def test_tui_ignores_the_project_file_keys_with_no_project(
    cli_json: CliHarness, run_tui: FakeRunTui
) -> None:
    cli_json.project_file("[keys]\na = 'a.key'\n")

    result = cli_json.invoke("--no-project", "tui", stdin_tty=True, stdout_tty=True)

    assert_exit(result, 0)
    [(_, key_paths)] = run_tui.calls
    assert key_paths == {}


def test_tui_with_noinput_exits_with_one(cli_json: CliHarness, run_tui: FakeRunTui) -> None:
    result = cli_json.invoke("--noinput", "tui", stdin_tty=True, stdout_tty=True)

    assert_exit(result, 1)
    assert "--noinput" in result.stderr
    assert run_tui.calls == []


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty"), [(False, True), (True, False), (False, False)]
)
def test_tui_without_a_terminal_exits_with_one(
    cli_json: CliHarness, run_tui: FakeRunTui, *, stdin_tty: bool, stdout_tty: bool
) -> None:
    result = cli_json.invoke("tui", stdin_tty=stdin_tty, stdout_tty=stdout_tty)

    assert_exit(result, 1)
    assert "terminal" in result.stderr
    assert run_tui.calls == []


def test_tui_without_a_connection_exits_with_one(cli_json: CliHarness, run_tui: FakeRunTui) -> None:
    result = cli_json.invoke("tui", stdin_tty=True, stdout_tty=True, connection=False)

    assert_exit(result, 1)
    assert "no connection configured" in result.stderr
    assert run_tui.calls == []


def test_tui_without_textual_exits_with_one_and_the_install_hint(
    cli_json: CliHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "textual", None)
    for module in [name for name in sys.modules if name.split(".")[:2] == _TUI_PACKAGE.split(".")]:
        monkeypatch.delitem(sys.modules, module)

    result = cli_json.invoke("tui", stdin_tty=True, stdout_tty=True)

    assert_exit(result, 1)
    assert "pip install 'environment-store[tui]'" in result.stderr


def test_tui_help_works_without_a_connection(cli_json: CliHarness) -> None:
    result = cli_json.invoke("tui", "--help", connection=False)

    assert_exit(result, 0)
    assert "tui" in result.stdout
