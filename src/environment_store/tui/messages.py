"""How the TUI reports errors: a notification with the error message only.

Library error messages never contain values or secrets (CONTRIBUTING §6). Their `hint` names
library parameters (`overwrite=True`, `generate_key_file()`); the TUI shows its own remedy in its
place, or none, never the library's. Markup is off, so text such as `[keys]` is shown as
written.
"""

from typing import Final

from textual.app import App

from environment_store.core.errors import EnvironmentStoreError, InvalidKeyFileError
from environment_store.formats.dotenv import DotenvValueError
from environment_store.library.files import OutputFileExistsError

__all__ = ["message_for", "notify_done", "notify_error", "notify_problem", "notify_reminder"]

_TITLE: Final = "Error"
_REMINDER_TITLE: Final = "Keep your key"
_REMINDER_SECONDS: Final = 30.0

# Error class -> the TUI's remedy, replacing the library's hint. Checked in order.
_TUI_HINTS: Final[tuple[tuple[type[EnvironmentStoreError], str], ...]] = (
    (InvalidKeyFileError, "create one with envs keygen"),
    (OutputFileExistsError, "export again and confirm replacing it"),
    (DotenvValueError, "choose the JSON or TOML format"),
)


def message_for(error: EnvironmentStoreError) -> str:
    """Return the message the TUI shows for a library error.

    An error with a library hint shows its detail with the TUI's remedy, or its detail alone when
    the TUI has none; every other error keeps its message.

    Args:
        error: The error.

    Returns:
        The message.
    """
    if error.hint is None:
        return str(error)
    for category, hint in _TUI_HINTS:
        if isinstance(error, category):
            return f"{error.detail}; {hint}"
    return error.detail


def notify_error(app: App[object], error: EnvironmentStoreError) -> None:
    """Show a library error.

    Args:
        app: The running app.
        error: The error; only its message (`message_for`) is shown.
    """
    notify_problem(app, message_for(error))


def notify_problem(app: App[object], message: str) -> None:
    """Show a problem the TUI found itself, e.g. an empty input.

    Args:
        app: The running app.
        message: What is wrong and how to fix it.
    """
    app.notify(message, title=_TITLE, severity="error", markup=False)


def notify_done(app: App[object], message: str) -> None:
    """Report a finished action, e.g. a created store.

    Args:
        app: The running app.
        message: What was done.
    """
    app.notify(message, markup=False)


def notify_reminder(app: App[object], message: str) -> None:
    """Show a reminder that must not be missed, such as an unsaved new key, for longer than usual.

    Args:
        app: The running app.
        message: The reminder.
    """
    app.notify(
        message,
        title=_REMINDER_TITLE,
        severity="warning",
        timeout=_REMINDER_SECONDS,
        markup=False,
    )
