"""Helpers of the Pilot tests: run an app under `asyncio.run` and read what it shows.

Plain `asyncio.run` around Pilot avoids a test dependency such as pytest-asyncio.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from textual.pilot import Pilot
from textual.widgets import DataTable, Input, TextArea
from textual.widgets._footer import FooterKey

from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp

__all__ = [
    "Scenario",
    "footer",
    "notifications",
    "rows",
    "run_app",
    "set_input",
    "set_text",
]

type Scenario = Callable[[Pilot[None], EnvironmentStoreApp], Awaitable[None]]


def run_app(
    store: EnvironmentStore,
    scenario: Scenario,
    *,
    key_paths: Mapping[str, Path] | None = None,
    app: EnvironmentStoreApp | None = None,
) -> EnvironmentStoreApp:
    """Run the TUI headless, drive it with `scenario`, and return the app afterwards."""
    tui = EnvironmentStoreApp(store, key_paths=key_paths or {}) if app is None else app

    async def main() -> None:
        async with tui.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await scenario(pilot, tui)

    asyncio.run(main())
    return tui


def rows(app: EnvironmentStoreApp) -> list[list[str]]:
    """The cells of the current screen's table, as text."""
    table = app.screen.query_one(DataTable)
    return [[str(cell) for cell in table.get_row_at(row)] for row in range(table.row_count)]


def footer(app: EnvironmentStoreApp) -> list[tuple[str, str]]:
    """The keys and descriptions the current screen's footer shows, in order."""
    return [(key.key, key.description) for key in app.screen.query(FooterKey)]


def notifications(app: EnvironmentStoreApp) -> list[str]:
    """Every notification message shown so far."""
    return [notification.message for notification in app._notifications]


async def set_input(pilot: Pilot[None], selector: str, value: str) -> None:
    """Replace an input's text on the current screen."""
    pilot.app.screen.query_one(selector, Input).value = value
    await pilot.pause()


async def set_text(pilot: Pilot[None], selector: str, value: str) -> None:
    """Replace a text area's text on the current screen."""
    pilot.app.screen.query_one(selector, TextArea).text = value
    await pilot.pause()
