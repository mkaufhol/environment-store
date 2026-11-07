"""Steps of the export dialogs for the Pilot tests (D56)."""

from textual.pilot import Pilot
from textual.widgets import SelectionList

from tests.tui.pilot import set_input

__all__ = ["export_to", "to_options", "to_path", "toggle"]


async def toggle(pilot: Pilot[None], *names: str) -> None:
    choice = pilot.app.screen.query_one(SelectionList)
    for name in names:
        choice.toggle(name)
        await pilot.pause()


async def to_options(pilot: Pilot[None], *names: str) -> None:
    await pilot.press("x")
    await pilot.pause()
    await toggle(pilot, *names)
    await pilot.press("ctrl+s")
    await pilot.pause()


async def to_path(pilot: Pilot[None], *names: str) -> None:
    await to_options(pilot, *names)
    await pilot.press("ctrl+s")
    await pilot.pause()


async def export_to(pilot: Pilot[None], path: str, *names: str) -> None:
    await to_path(pilot, *names)
    await set_input(pilot, "#path", path)
    await pilot.press("enter")
    await pilot.pause()
