"""`-h` is a shorthand for `--help` on `envs` and on every command (D48).

Like `--help`, `-h` needs neither a connection nor a valid project file (D44).
"""

from typing import Final

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app
from tests.support.cli import CliHarness, assert_exit

_BROKEN: Final = "stores = 'not a list'"


def _group() -> EnvsGroup:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)
    return group


_COMMANDS: Final = sorted(_group().commands)


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_root_help_flags_print_the_help_and_exit_zero(cli_json: CliHarness, flag: str) -> None:
    result = cli_json.invoke(flag, connection=False)

    assert_exit(result, 0)
    assert result.stdout.startswith("Usage: ")
    assert result.stderr == ""


def test_root_short_help_equals_the_long_help(cli_json: CliHarness) -> None:
    short = cli_json.invoke("-h", connection=False)
    long = cli_json.invoke("--help", connection=False)

    assert short.stdout == long.stdout


@pytest.mark.parametrize("command", _COMMANDS)
def test_every_command_prints_its_help_for_dash_h(cli_json: CliHarness, command: str) -> None:
    result = cli_json.invoke(command, "-h", connection=False)

    assert_exit(result, 0)
    assert result.stdout.split("\n", 1)[0].split()[2] == command
    assert result.stdout == cli_json.invoke(command, "--help", connection=False).stdout
    assert result.stderr == ""


@pytest.mark.parametrize("command", [None, *_COMMANDS])
def test_dash_h_needs_no_connection_and_ignores_a_broken_project_file(
    cli_json: CliHarness, command: str | None
) -> None:
    cli_json.project_file(_BROKEN)
    args = ["-h"] if command is None else [command, "-h"]

    result = cli_json.invoke(*args, connection=False)

    assert_exit(result, 0)
    assert "Usage:" in result.stdout
    assert result.stderr == ""


def test_both_help_names_are_listed_in_the_help(cli_json: CliHarness) -> None:
    result = cli_json.invoke("-h", connection=False)

    assert "-h, --help" in result.stdout


@pytest.mark.parametrize("command", [None, *_COMMANDS])
def test_no_option_other_than_help_uses_dash_h(command: str | None) -> None:
    group = _group()
    target = group if command is None else group.commands[command]

    owners = [param.name for param in target.params if "-h" in (*param.opts, *param.secondary_opts)]

    assert owners == []
