"""`envs` has exactly its twenty commands, and the help lists each of them."""

from typing import Final

from typer.main import get_command
from typer.testing import CliRunner

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app

_COMMANDS: Final = frozenset(
    {
        "ls-store",
        "create-store",
        "rm-store",
        "cp-store",
        "mv-store",
        "ls",
        "get",
        "set",
        "rm",
        "import",
        "export",
        "export-shell",
        "export-credentials",
        "run",
        "keygen",
        "rekey",
        "encrypt",
        "migrate",
        "tui",
        "completion",
    }
)


def _registered_commands() -> set[str]:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)
    return set(group.commands)


def test_expected_commands_are_twenty() -> None:
    assert len(_COMMANDS) == 20


def test_registered_commands_are_exactly_the_expected_commands() -> None:
    assert _registered_commands() == _COMMANDS


def test_help_lists_every_expected_command() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    listed = {line.split()[0] for line in result.stdout.splitlines() if line.startswith("  ")}
    assert listed >= _COMMANDS
