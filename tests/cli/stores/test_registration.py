"""The store commands are registered on `envs` with the envs command class (spec §6.1, PD 10)."""

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsCommand, EnvsGroup
from environment_store.cli.app import app
from tests.support.cli import CliHarness, assert_exit

_COMMANDS = ("ls-store", "create-store", "rm-store", "cp-store", "mv-store")


@pytest.mark.parametrize("name", _COMMANDS)
def test_store_command_is_registered_as_an_envs_command(name: str) -> None:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)

    assert isinstance(group.commands[name], EnvsCommand)


@pytest.mark.parametrize("name", _COMMANDS)
def test_store_command_help_works_without_a_connection(cli_json: CliHarness, name: str) -> None:
    result = cli_json.invoke(name, "--help", connection=False)

    assert_exit(result, 0)
    assert name in result.stdout
