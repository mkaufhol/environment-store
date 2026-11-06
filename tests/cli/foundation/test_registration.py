"""Every registered command uses the envs command classes (PD 10), also C2-C4's once merged."""

import typer
from typer.main import get_command

from environment_store.cli._typer import EnvsCommand, EnvsGroup
from environment_store.cli.app import app, build_app
from environment_store.cli.options import StoresArg


def _commands(application: typer.Typer) -> dict[str, object]:
    group = get_command(application)
    assert isinstance(group, EnvsGroup)
    return dict(group.commands)


def test_the_app_is_an_envs_group_with_commands() -> None:
    assert "migrate" in _commands(app)


def test_every_registered_command_resolves_settings_through_envs_command() -> None:
    offenders = [
        name for name, command in _commands(app).items() if not isinstance(command, EnvsCommand)
    ]

    assert offenders == []


def test_the_check_finds_a_command_registered_without_the_envs_class() -> None:
    application = build_app()

    @application.command("plain")
    def plain(stores: StoresArg = None) -> None:
        del stores

    assert not isinstance(_commands(application)["plain"], EnvsCommand)


def test_build_app_returns_a_new_app_each_time() -> None:
    assert build_app() is not build_app()
