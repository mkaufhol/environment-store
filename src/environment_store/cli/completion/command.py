"""`envs completion <shell>`: print the shell completion script.

envs never edits shell configuration files; the user adds one line, e.g.
`eval "$(envs completion zsh)"`. Like `keygen`, the command reads neither the connection nor
the project file, so a broken project file cannot stop it. The script completes the program
name envs was run as, so `environment-store completion zsh` completes `environment-store`.
"""

from enum import StrEnum
from typing import Annotated

import typer

from environment_store.cli._typer import OfflineCommand
from environment_store.cli.completion.protocol import program_name, script
from environment_store.cli.output import out

__all__ = ["Shell", "completion", "register"]


class Shell(StrEnum):
    """The shells with a completion script."""

    BASH = "bash"
    ZSH = "zsh"
    FISH = "fish"


ShellArg = Annotated[
    Shell,
    typer.Argument(metavar="SHELL", help="bash (4.4 or newer), zsh or fish.", show_default=False),
]


def completion(ctx: typer.Context, shell: ShellArg) -> None:
    """Print the shell completion script for bash, zsh or fish.

    Add it to the shell's start-up file: eval "$(envs completion zsh)" in ~/.zshrc,
    eval "$(envs completion bash)" in ~/.bashrc (bash 4.4 or newer), or
    envs completion fish > ~/.config/fish/completions/envs.fish.
    """
    root = ctx.find_root()
    out(script(root.command, shell.value, program_name(root.info_name)), newline=False)


def register(app: typer.Typer) -> None:
    """Register `completion` on the `envs` app; it reads no settings (`OfflineCommand`).

    Args:
        app: The `envs` app.
    """
    app.command("completion", cls=OfflineCommand)(completion)
