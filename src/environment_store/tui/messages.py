"""How the TUI reports errors: a notification with the error message only.

Library error messages never contain values or secrets (CONTRIBUTING §6), and nothing else is
added to them. Markup is off, so text such as `[keys]` is shown as written.
"""

from typing import Final

from textual.app import App

from environment_store.core.errors import EnvironmentStoreError

__all__ = ["notify_error", "notify_problem"]

_TITLE: Final = "Error"


def notify_error(app: App[object], error: EnvironmentStoreError) -> None:
    """Show a library error.

    Args:
        app: The running app.
        error: The error; only its message is shown.
    """
    notify_problem(app, str(error))


def notify_problem(app: App[object], message: str) -> None:
    """Show a problem the TUI found itself, e.g. an empty input.

    Args:
        app: The running app.
        message: What is wrong and how to fix it.
    """
    app.notify(message, title=_TITLE, severity="error", markup=False)
