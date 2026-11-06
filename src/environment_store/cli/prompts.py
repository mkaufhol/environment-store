"""`TerminalPrompter`: the CLI's prompter, on stderr only (D3, PD 20, PD 21).

typer's `prompt` / `confirm` are not used: they write part of the prompt and the echo to stdout
and turn Ctrl-C into an abort with exit code 1. Here hidden input goes through `getpass` on
stderr, questions are written to stderr and answers read from stdin, so stdout stays clean for
`$(envs get ...)` and `eval "$(envs export-shell ...)"`. Ctrl-C is not caught: typer turns it
into exit code 130. End of input aborts (exit code 1).
"""

import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import typer

from environment_store.core.errors import ValidationError

__all__ = ["TerminalPrompter", "read_hidden", "read_line", "write"]

_REPEAT_PROMPT: Final = "Repeat to confirm: "
_MISMATCH: Final = "values do not match\n"
_ATTEMPTS: Final = 3
_YES: Final[frozenset[str]] = frozenset({"y", "yes"})


def read_hidden(prompt: str) -> str:
    """Read a line without echo; the prompt goes to stderr (looked up at call time).

    Args:
        prompt: The prompt text.

    Returns:
        The answer without its line ending.
    """
    return getpass.getpass(prompt, stream=sys.stderr)


def read_line() -> str:
    """Read one line from stdin (looked up at call time).

    Returns:
        The line with its line ending; `""` at end of input.
    """
    return sys.stdin.readline()


def write(text: str) -> None:
    """Write text to stderr and flush it (looked up at call time).

    Args:
        text: The text.
    """
    sys.stderr.write(text)
    sys.stderr.flush()


@dataclass(frozen=True, slots=True, kw_only=True)
class TerminalPrompter:
    """A `Prompter` on the terminal; the three callables are the test seam.

    Attributes:
        read_hidden: Reads a hidden answer after showing a prompt.
        read_line: Reads a visible answer line.
        write: Shows text to the user.
    """

    read_hidden: Callable[[str], str] = read_hidden
    read_line: Callable[[], str] = read_line
    write: Callable[[str], None] = write

    def secret(self, prompt: str) -> str:
        """Ask for a secret with hidden input.

        Args:
            prompt: The prompt text, shown as given.

        Returns:
            The answer.

        Raises:
            typer.Abort: End of input.
        """
        return self._hidden(prompt)

    def new_secret(self, prompt: str) -> str:
        """Ask for a new secret twice; on a mismatch ask again, at most three times.

        Args:
            prompt: The prompt text of the first question.

        Returns:
            The answer.

        Raises:
            ValidationError: The two entries differed three times; neither is shown.
            typer.Abort: End of input.
        """
        for _ in range(_ATTEMPTS):
            first = self._hidden(prompt)
            if self._hidden(_REPEAT_PROMPT) == first:
                return first
            self.write(_MISMATCH)
        message = f"the two entries did not match {_ATTEMPTS} times; nothing was changed"
        raise ValidationError(message)

    def confirm(self, question: str) -> bool:
        """Ask a yes/no question; only `y` or `yes` (any case) is yes.

        Args:
            question: The question.

        Returns:
            Whether the user answered yes.

        Raises:
            typer.Abort: End of input.
        """
        self.write(f"{question} [y/N]: ")
        line = self.read_line()
        if not line:
            raise typer.Abort
        return line.strip().lower() in _YES

    def _hidden(self, prompt: str) -> str:
        try:
            return self.read_hidden(prompt)
        except EOFError:
            raise typer.Abort from None
