"""docs/tui.md shows the footers the TUI really shows.

Every screen's footer lists the keys that work there, and it changes with the focus: a path
input adds `tab Complete path`. The test drives the TUI headless through every screen and
dialog, collects each footer, and compares them with the guide in both directions.
"""

import re
from pathlib import Path
from typing import Final

import pytest
from textual.pilot import Pilot
from textual.widgets import DataTable, Input
from textual.widgets._footer import FooterKey

from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from tests.support.cli import connection_for
from tests.support.kdf import CheapKdf
from tests.tui.pilot import run_app

_GUIDE: Final = Path(__file__).parents[2] / "docs" / "tui.md"
_FENCE: Final = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
# A footer as the guide draws it: key/description pairs, ending in Quit or Cancel.
_FOOTER_LINE: Final = re.compile(r"^\s*((?:⏎|\^s|space|y) \S.*\b(?:Quit|Cancel))\s*$")


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _footer(app: EnvironmentStoreApp) -> str:
    keys = app.screen.query(FooterKey)
    return _normalised(" ".join(f"{key.key_display or key.key} {key.description}" for key in keys))


def _focus_input(app: EnvironmentStoreApp, widget_id: str) -> None:
    app.screen.query_one(f"#{widget_id}", Input).focus()


def _select_row(app: EnvironmentStoreApp, row: int) -> None:
    table = app.screen.query_one(DataTable)
    table.focus()
    table.move_cursor(row=row)


async def _visit(pilot: Pilot[None], app: EnvironmentStoreApp, seen: list[str]) -> None:
    async def note() -> None:
        await pilot.pause()
        seen.append(_footer(app))

    async def press(*keys: str) -> None:
        await pilot.press(*keys)
        await pilot.pause()

    await note()  # stores
    await press("a")
    await note()  # create: name
    for index, field in ((1, "generate-path"), (2, "key-path"), (3, "passphrase-input")):
        app.screen.query_one("#encryption").focus()
        await note()  # create: encryption choice
        await press("home", *["down"] * index, "enter")
        _focus_input(app, field)
        await note()
    await press("escape", "d")
    await note()  # remove
    await press("escape", "x")
    await note()  # export, step 1
    await press("space", "ctrl+s")
    await note()  # export, step 2
    await press("ctrl+s")
    await note()  # export, step 3
    await press("escape")
    _select_row(app, 1)
    await press("enter")  # open 'prod', encrypted
    await note()  # unlock: key file
    _focus_input(app, "passphrase")
    await note()  # unlock: passphrase
    await press("escape")
    _select_row(app, 0)
    await press("enter")  # open 'base', plain
    await note()  # variables
    await press("a")
    await note()  # add
    await press("escape", "e")
    await note()  # edit
    await press("escape", "d")
    await note()  # confirm


@pytest.fixture(scope="module")
def shown_footers(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Every footer the TUI shows on the way through its screens and dialogs."""
    root = tmp_path_factory.mktemp("tui")
    seen: list[str] = []
    with EnvironmentStore(connection_for(root, "json"), kdf_params_factory=CheapKdf()) as store:
        store.create_store("base")
        store.set("base", "DEBUG", "true")
        store.create_store("prod", encrypt=True, key=Passphrase(text="secret passphrase"))

        async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
            await _visit(pilot, app, seen)

        run_app(store, scenario)
    return seen


def _documented_footer_lines() -> list[str]:
    blocks = _FENCE.findall(_GUIDE.read_text(encoding="utf-8"))
    lines = [line for block in blocks for line in block.splitlines()]
    return [_normalised(match.group(1)) for line in lines if (match := _FOOTER_LINE.match(line))]


def test_the_scenario_reaches_every_screen_and_dialog(shown_footers: list[str]) -> None:
    assert len(shown_footers) == 18
    assert all(shown_footers)


def test_every_footer_the_tui_shows_is_in_the_guide(shown_footers: list[str]) -> None:
    guide = _normalised(_GUIDE.read_text(encoding="utf-8"))
    assert [footer for footer in dict.fromkeys(shown_footers) if footer not in guide] == []


def test_every_footer_drawn_in_the_guide_is_one_the_tui_shows(shown_footers: list[str]) -> None:
    documented = _documented_footer_lines()
    assert documented
    assert [line for line in documented if line not in shown_footers] == []
