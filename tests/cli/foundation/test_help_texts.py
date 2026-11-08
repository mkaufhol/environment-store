"""Option help texts: each command describes the behaviour it has."""

import pytest
import typer
from typer.core import TyperGroup, TyperOption

from environment_store.cli.app import app


def _help(command: str | None, option: str) -> str:
    root = typer.main.get_command(app)
    assert isinstance(root, TyperGroup)
    target = root if command is None else root.commands[command]
    helps = [
        param.help or ""
        for param in target.params
        if isinstance(param, TyperOption) and option in param.opts
    ]
    assert len(helps) == 1, f"{command} has no option {option}"
    return helps[0]


@pytest.mark.parametrize("command", ["export-shell", "run"])
def test_nested_help_of_shell_and_run_describes_the_prefix_only(command: str) -> None:
    text = _help(command, "--nested")

    assert "STORE__NAME" in text
    assert "table" not in text


def test_nested_help_of_export_names_both_forms() -> None:
    text = _help("export", "--nested")

    assert "STORE__NAME" in text
    assert "table" in text


def test_file_help_of_import_names_stdin_only() -> None:
    text = _help("import", "-f")

    assert "stdin" in text
    assert "stdout" not in text


def test_file_help_of_export_names_stdout_only() -> None:
    text = _help("export", "-f")

    assert "stdout" in text
    assert "stdin" not in text


def test_noinput_help_names_both_outcomes() -> None:
    text = _help(None, "--noinput")

    assert "exit code 4" in text
    assert "-y" in text
    assert "exit code 1" in text


def test_source_help_of_ls_says_it_works_without_values() -> None:
    text = _help("ls", "--source")

    assert "without -v" in text
    assert "NAME" in text


@pytest.mark.parametrize("command", ["cp-store", "mv-store"])
def test_copy_help_says_the_encryption_options_are_mutually_exclusive(command: str) -> None:
    root = typer.main.get_command(app)
    assert isinstance(root, TyperGroup)

    text = " ".join((root.commands[command].help or "").split())

    assert "--plain, --new-key, --generate-key and --passphrase are mutually exclusive" in text
