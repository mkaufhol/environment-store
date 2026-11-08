"""Path completion for every path input of the TUI.

`PathSuggester` suggests the first existing file or directory that completes what was typed:
`~` is expanded for the lookup but kept in the suggestion (only at the start, like the CLI's
`-k`: `./~/a` names a directory called `~`), directories end in `/`, matching is
case-sensitive, hidden entries are suggested only once a `.` is typed, and a directory that
cannot be read suggests nothing. `PathInput` is an `Input` with that suggester whose `Tab`
accepts a shown suggestion (`→` does too, as in every `Input`) and otherwise moves the focus.
"""

import asyncio
import os
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar, override

from textual.binding import Binding, BindingType
from textual.suggester import Suggester
from textual.widgets import Input

from environment_store.core.errors import ValidationError

__all__ = ["PathInput", "PathSuggester", "complete_path", "expand_path"]


def complete_path(typed: str) -> str | None:
    """Return the first existing entry that completes a typed path.

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
        directory = _expand_home(typed_directory or ".")
        with os.scandir(directory) as entries:
            name = _first_completion(entries, prefix)
    except (OSError, RuntimeError, ValueError):
        # Unreadable or missing directory, unknown "~user", or a NUL character.
        return None
    return None if name is None else f"{typed_directory}{name}"


def _first_completion(entries: Iterable[os.DirEntry[str]], prefix: str) -> str | None:
    """Return the first entry name (with `/` for a directory) that is longer than `prefix`.

    One pass without sorting, and only the exact match and the chosen entry are asked whether
    they are directories, so a large directory stays cheap on every keystroke.
    """
    exact: os.DirEntry[str] | None = None
    shortest: os.DirEntry[str] | None = None
    for entry in entries:
        name = entry.name
        if not name.startswith(prefix) or (name.startswith(".") and not prefix.startswith(".")):
            continue
        if name == prefix:
            exact = entry
        elif shortest is None or name < shortest.name:
            shortest = entry
    # The exact match sorts first, but only completes as a directory ("docs" to "docs/").
    if exact is not None and exact.is_dir():
        return f"{exact.name}/"
    if shortest is None:
        return None
    return f"{shortest.name}/" if shortest.is_dir() else shortest.name


def expand_path(text: str, *, what: str) -> Path:
    """Turn the text of a path input into a path: trimmed, with a leading `~` expanded.

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
        return _expand_home(stripped)
    except RuntimeError as err:
        message = f"{what} path '{stripped}' names an unknown home directory"
        raise ValidationError(message) from err


def _expand_home(text: str) -> Path:
    """Expand a leading `~`, as `-k` of the CLI does.

    Checked on the text: `Path` drops a leading `./`, so `Path("./~/a")` is `Path("~/a")`
    and `expanduser` would wrongly read it as the home directory.

    Raises:
        RuntimeError: The text names an unknown user's home directory.
    """
    path = Path(text)
    return path.expanduser() if text.startswith("~") else path


class PathSuggester(Suggester):
    """Suggests existing files and directories; never cached, the disk changes.

    The lookup runs in a worker thread, so a slow or hung directory (a network mount, an
    automount path) never blocks the event loop and freezes the TUI.
    """

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
        return await asyncio.to_thread(complete_path, value)


class PathInput(Input):
    """An input for a path: suggests completions, `Tab` accepts them."""

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
