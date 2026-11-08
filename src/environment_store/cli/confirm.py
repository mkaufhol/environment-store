"""Confirmations of destructive commands."""

import typer

from environment_store.cli.state import get_state
from environment_store.core.errors import ValidationError

__all__ = ["require_confirmation"]


def require_confirmation(ctx: typer.Context, question: str, *, yes: bool) -> None:
    """Proceed only when confirmed: `-y`, or a yes on a terminal.

    Args:
        ctx: The command's context.
        question: The question, e.g. `Delete store 'a'?`.
        yes: Whether `-y/--yes` was given.

    Raises:
        typer.Abort: The user answered no (exit code 1).
        ValidationError: Not interactive (no terminal or `--noinput`) and no `-y` (exit 1).
    """
    if yes:
        return
    state = get_state(ctx)
    if not state.interactive():
        message = f"{question} Confirm with -y/--yes (no terminal to ask, or --noinput)"
        raise ValidationError(message)
    if not state.prompter().confirm(question):
        raise typer.Abort
