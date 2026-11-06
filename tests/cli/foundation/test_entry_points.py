"""Entry points `envs` / `environment-store`, `python -m` and the `cli` extra guard (D20)."""

import importlib
import runpy
import subprocess
import sys
from importlib.metadata import entry_points

import pytest

from environment_store.core.errors import MissingExtraError


def test_both_console_scripts_run_main() -> None:
    scripts = {entry.name: entry.value for entry in entry_points(group="console_scripts")}

    assert scripts["envs"] == "environment_store.cli:main"
    assert scripts["environment-store"] == "environment_store.cli:main"


def _run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int | str | None:
    from environment_store.cli import main  # noqa: PLC0415 - imported per test on purpose

    monkeypatch.setattr(sys, "argv", ["envs", *args])
    with pytest.raises(SystemExit) as exited:
        main()
    return exited.value.code


def test_main_exits_with_the_command_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_main(monkeypatch, "--no-project", "migrate")

    assert code == 1
    assert "no connection configured" in capsys.readouterr().err


def test_main_exits_with_zero_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run_main(monkeypatch, "--version") == 0
    assert capsys.readouterr().out.startswith("environment-store ")


def test_main_without_typer_prints_the_install_hint_and_exits_with_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "typer", None)
    monkeypatch.delitem(sys.modules, "environment_store.cli.app")

    code = _run_main(monkeypatch, "--version")

    assert code == 1
    assert "pip install 'environment-store[cli]'" in capsys.readouterr().err


def test_importing_the_app_without_typer_raises_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "typer", None)
    monkeypatch.delitem(sys.modules, "environment_store.cli.app")

    with pytest.raises(MissingExtraError) as raised:
        importlib.import_module("environment_store.cli.app")

    assert raised.value.extra == "cli"


def test_python_dash_m_runs_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["envs", "--version"])
    monkeypatch.delitem(sys.modules, "environment_store.cli.__main__", raising=False)

    with pytest.raises(SystemExit) as exited:
        runpy.run_module("environment_store.cli.__main__", run_name="__main__")

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("environment-store ")


def test_importing_the_main_module_does_not_run_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "environment_store.cli.__main__", raising=False)

    module = importlib.import_module("environment_store.cli.__main__")

    assert module.main.__name__ == "main"


def test_cli_package_imports_no_typer() -> None:
    code = "import sys, environment_store.cli\nprint('typer' in sys.modules)"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout == "False\n"
