"""Interactive prompts: the `Prompter` protocol and the `getpass` implementation (D3, PD 11).

Frontends inject a prompter; `None` means "never prompt" (non-interactive use or `--noinput`,
D35). `GetpassPrompter` is the library one-liner's prompter and the only place in the library
that talks to the terminal.
"""

import getpass
import sys
from typing import Final, Protocol, TextIO

from environment_store.core.errors import ValidationError

__all__ = ["GetpassPrompter", "Prompter"]

_YES: Final[frozenset[str]] = frozenset({"y", "yes"})
_REPEAT_PROMPT: Final = "Repeat to confirm: "


class Prompter(Protocol):
    """Asks the user for secrets and confirmations."""

    def secret(self, prompt: str) -> str:
        """Ask for a secret with hidden input.

        Args:
            prompt: The prompt text.

        Returns:
            The answer.
        """
        ...

    def new_secret(self, prompt: str) -> str:
        """Ask for a new secret twice, hidden; both answers must match.

        Args:
            prompt: The prompt text of the first question.

        Returns:
            The answer.
        """
        ...

    def confirm(self, question: str) -> bool:
        """Ask a yes/no question; anything but yes is no.

        Args:
            question: The question.

        Returns:
            Whether the user answered yes.
        """
        ...


class GetpassPrompter:
    """A `Prompter` on `getpass.getpass` (prompts on the terminal or stderr, PD 11)."""

    _input_stream: TextIO | None
    _error_stream: TextIO | None

    def __init__(
        self, *, input_stream: TextIO | None = None, error_stream: TextIO | None = None
    ) -> None:
        """Create the prompter.

        Args:
            input_stream: Where `confirm` reads the answer; `None` for `sys.stdin`.
            error_stream: Where `confirm` writes the question; `None` for `sys.stderr`.
        """
        self._input_stream = input_stream
        self._error_stream = error_stream

    def secret(self, prompt: str) -> str:
        """Ask for a secret with hidden input.

        Args:
            prompt: The prompt text.

        Returns:
            The answer.
        """
        return getpass.getpass(prompt)

    def new_secret(self, prompt: str) -> str:
        """Ask for a new secret twice, hidden.

        Args:
            prompt: The prompt text of the first question.

        Returns:
            The answer.

        Raises:
            ValidationError: The two answers differ; neither is shown.
        """
        first = getpass.getpass(prompt)
        if getpass.getpass(_REPEAT_PROMPT) != first:
            message = "the two entries do not match; nothing was changed"
            raise ValidationError(message)
        return first

    def confirm(self, question: str) -> bool:
        """Ask a yes/no question on stderr and read the answer line from stdin.

        Args:
            question: The question.

        Returns:
            Whether the answer is `y` or `yes` (case-insensitive).
        """
        errors = sys.stderr if self._error_stream is None else self._error_stream
        errors.write(f"{question} [y/N] ")
        errors.flush()
        answer = (sys.stdin if self._input_stream is None else self._input_stream).readline()
        return answer.strip().lower() in _YES
