"""Drive the completion protocol in-process, as the scripts of bash, zsh and fish do."""

import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import typer
from typer.testing import CliRunner, Result

from environment_store.cli.app import app as envs
from environment_store.cli.runtime import Runtime
from tests.support.cli import CliHarness

__all__ = ["Item", "Shell", "complete", "parse"]

type Shell = Literal["bash", "zsh", "fish"]


@dataclass(frozen=True, slots=True)
class Item:
    """One candidate: its type (`plain`, `file`, `dir`) and its value."""

    type: str
    value: str


def _environment(shell: Shell, words: list[str], incomplete: str) -> dict[str, str]:
    if shell == "fish":
        line = shlex.join(words) + " " + incomplete
        return {"COMP_WORDS": line, "COMP_CWORD": incomplete}
    # The scripts join the words with spaces, like "${COMP_WORDS[*]}".
    return {
        "COMP_WORDS": " ".join([*map(shlex.quote, words), shlex.quote(incomplete)]),
        "COMP_CWORD": str(len(words)),
    }


def complete(  # noqa: PLR0913 - every boundary of a completion request is a keyword
    cli: CliHarness,
    *args: str,
    incomplete: str = "",
    shell: Shell = "bash",
    connection: bool = True,
    prog_name: str = "envs",
    env: Mapping[str, str] | None = None,
    runtime: Runtime | None = None,
    app: typer.Typer = envs,
) -> Result:
    """Ask for the candidates of `incomplete` after `prog_name -c <connection> args...`."""
    words = [prog_name, *(("-c", cli.connection) if connection else ()), *args]
    variable = f"_{prog_name}_COMPLETE".replace("-", "_").upper()
    environment = {variable: f"{shell}_complete", **_environment(shell, words, incomplete)}
    return CliRunner().invoke(
        app,
        [],
        env={**environment, **(env or {})},
        prog_name=prog_name,
        obj=cli.runtime() if runtime is None else runtime,
    )


def parse(result: Result, shell: Shell = "bash") -> list[Item]:
    """The candidates of a successful, silent answer."""
    assert result.exit_code == 0, (result.exit_code, result.stderr, result.exception)
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    if shell == "zsh":
        return [Item(lines[i], lines[i + 1]) for i in range(0, len(lines), 3)]
    items = []
    for line in lines:
        kind, _, rest = line.partition(",")
        items.append(Item(kind, rest.partition("\t")[0]))
    return items
