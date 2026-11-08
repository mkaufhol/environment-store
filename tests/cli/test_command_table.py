"""`envs` has exactly the commands of spec §6.1 (IMPLEMENTATION-PLAN.md §6.2)."""

import re
from pathlib import Path
from typing import Final

from typer.main import get_command
from typer.testing import CliRunner

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app

_SPEC: Final = Path(__file__).parents[2] / "SPEC-V2.md"
_SECTION: Final = "### 6.1 Command overview"
# A table row's first cell starts with the command in backticks: | `cp-store <src> <dst>` | …
_ROW: Final = re.compile(r"^\| `([a-z-]+)[^`]*` \|")


def _spec_commands() -> set[str]:
    lines = _SPEC.read_text(encoding="utf-8").splitlines()
    start = lines.index(_SECTION) + 1
    commands: set[str] = set()
    for line in lines[start:]:
        if line.startswith("#"):
            break
        match = _ROW.match(line)
        if match is not None:
            commands.add(match.group(1))
    return commands


def _registered_commands() -> set[str]:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)
    return set(group.commands)


def test_spec_command_overview_lists_nineteen_commands() -> None:
    assert len(_spec_commands()) == 19


def test_registered_commands_are_exactly_the_spec_command_overview() -> None:
    assert _registered_commands() == _spec_commands()


def test_help_lists_every_command_of_the_spec_command_overview() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    listed = {line.split()[0] for line in result.stdout.splitlines() if line.startswith("  ")}
    assert _spec_commands() <= listed
