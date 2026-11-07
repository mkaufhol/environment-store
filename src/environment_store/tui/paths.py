"""Path completion for every path input of the TUI (D57).

`PathSuggester` suggests the first existing file or directory that completes what was typed:
`~` is expanded for the lookup but kept in the suggestion, directories end in `/`, matching is
case-sensitive, hidden entries are suggested only once a `.` is typed, and a directory that
cannot be read suggests nothing. `PathInput` is an `Input` with that suggester whose `Tab`
accepts a shown suggestion (`→` does too, as in every `Input`) and otherwise moves the focus.
"""

import os
from pathlib import Path
from typing import ClassVar, override

from textual.binding import Binding, BindingType
from textual.suggester import Suggester
from textual.widgets import Input

from environment_store.core.errors import ValidationError

__all__ = ["PathInput", "PathSuggester", "complete_path", "expand_path"]


def complete_path(typed: str) -> str | None:
    """Return the first existing entry that completes a typed path (D57).

    Args:
        typed: The text of the path input.

    Returns:
        The typed directory part followed by the entry's name (and `/` for a directory), or
        `None` when no entry makes the text longer.
    """
    head, separator, prefix = typed.rpartition("/")
    if not separator and typed.startswith("~"):
        # A bare "~user" is not looked up; "~" alone completes to the home directory.
        return "~/" if typed == "~" else None
    typed_directory = f"{head}/" if separator else ""
    try:
        directory = Path(typed_directory or ".").expanduser()
        with os.scandir(directory) as entries:
            candidates = sorted(
                (entry.name, entry.is_dir())
                for entry in entries
                if entry.name.startswith(prefix)
                and (prefix.startswith(".") or not entry.name.startswith("."))
            )
    except (OSError, RuntimeError, ValueError):
        # Unreadable or missing directory, unknown "~user", or a NUL character.
        return None
    for name, is_directory in candidates:
        completion = f"{typed_directory}{name}{'/' if is_directory else ''}"
        if len(completion) > len(typed):
            return completion
    return None


def expand_path(text: str, *, what: str) -> Path:
    """Turn the text of a path input into a path: trimmed, with `~` expanded.

    Args:
        text: The typed path.
        what: What the path is for, e.g. `key file`, named in the error.

    Returns:
        The path.

    Raises:
        ValidationError: The path names an unknown user's home directory.
    """
    stripped = text.strip()
    try:
        return Path(stripped).expanduser()
    except RuntimeError as err:
        message = f"{what} path '{stripped}' names an unknown home directory"
        raise ValidationError(message) from err


class PathSuggester(Suggester):
    """Suggests existing files and directories (D57); never cached, the disk changes."""

    def __init__(self) -> None:
        """Create the suggester: case-sensitive, without a cache."""
        super().__init__(use_cache=False, case_sensitive=True)

    @override
    async def get_suggestion(self, value: str) -> str | None:
        """Complete a typed path.

        Args:
            value: The input's text.

        Returns:
            The completed path, or `None`.
        """
        return complete_path(value)


class PathInput(Input):
    """An input for a path: suggests completions, `Tab` accepts them (D57)."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("tab", "complete", "Complete path")]

    def __init__(
        self,
        value: str = "",
        *,
        placeholder: str = "",
        id: str | None = None,  # noqa: A002 - the name Textual uses
    ) -> None:
        """Create the input.

        Args:
            value: The initial text.
            placeholder: Shown while it is empty.
            id: The widget id.
        """
        super().__init__(value, placeholder=placeholder, id=id, suggester=PathSuggester())

    def action_complete(self) -> None:
        """Accept the shown suggestion, or move the focus on like `Tab` elsewhere."""
        if self.cursor_at_end and len(self._suggestion) > len(self.value):
            self.action_cursor_right()
        else:
            self.screen.focus_next()
