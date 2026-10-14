import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Tree

from environment_store.adapters.json.json_file_adapter import JsonFileAdapter
from environment_store.core import EnvironmentStoreManager
from environment_store.tui.app import ConfirmDeleteLevel, EnvironmentStoreApp


@pytest.fixture
def manager(tmp_path):
    m = EnvironmentStoreManager(JsonFileAdapter(str(tmp_path / "s.json")))
    m.set_variable("ROOT", "r")
    m.set_variable("A", "org", organisation="acme")
    m.set_variable("B", "proj", organisation="acme", project="web")
    return m


def test_tree_lists_hierarchy_and_table_follows_selection(manager):
    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(Tree)
            assert [str(n.label) for n in tree.root.children] == ["acme"]
            table = app.query_one(DataTable)
            assert table.row_count == 1  # root variable
            await pilot.press("down")
            await pilot.pause()
            assert app.path == ("acme",)
            assert table.get_row("A") == ["A", "***"]
            await pilot.press("v")
            assert table.get_row("A") == ["A", "org"]
            await pilot.press("r")
            assert table.row_count == 2  # org + root

    asyncio.run(scenario())


def test_add_and_delete_variable(manager):
    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("a")
            await pilot.pause()
            app.screen.query_one("#name", Input).value = "NEW"
            app.screen.query_one("#value", Input).value = "val"
            await pilot.click("#save")
            await pilot.pause()
            assert manager.get_variable("NEW") == "val"
            app.query_one(DataTable).move_cursor(row=0)
            await pilot.press("d")
            await pilot.pause()
            await pilot.click("#yes")
            await pilot.pause()
            assert len(manager.get_variables()) == 1

    asyncio.run(scenario())


def test_new_child_level(manager):
    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # acme
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            app.screen.query_one("#level", Input).value = "api"
            app.screen.query_one("#name", Input).value = "KEY"
            app.screen.query_one("#value", Input).value = "v"
            await pilot.click("#save")
            await pilot.pause()
            assert manager.get_variable("KEY", organisation="acme", project="api") == "v"
            assert set(manager.get_projects("acme")) == {"web", "api"}
            assert app.path == ("acme", "api")

    asyncio.run(scenario())


def test_delete_level_requires_typing_name(manager):
    manager.set_variable("C", "env", organisation="acme", project="web", environment="dev")

    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # acme
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            button = app.screen.query_one("#yes")
            assert button.disabled
            app.screen.query_one("#confirm", Input).value = "wrong"
            await pilot.pause()
            assert button.disabled
            app.screen.query_one("#confirm", Input).value = "acme"
            await pilot.pause()
            assert not button.disabled
            await pilot.click("#yes")
            await pilot.pause()
            assert manager.get_organisations() == []
            assert [v.name for v in manager.get_variables()] == ["ROOT"]
            assert app.path == ()
            assert len(app.query_one(Tree).root.children) == 0

    asyncio.run(scenario())


def test_delete_level_cancel_and_root(manager):
    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")  # root: refused
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmDeleteLevel)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.click("#no")
            await pilot.pause()
            assert manager.get_organisations() == ["acme"]

    asyncio.run(scenario())


def test_delete_nested_level_refreshes_parent(manager):
    async def scenario():
        app = EnvironmentStoreApp(manager)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._reveal(("acme", "web"))
            await pilot.pause()
            assert app.path == ("acme", "web")
            await pilot.press("x")
            await pilot.pause()
            app.screen.query_one("#confirm", Input).value = "web"
            await pilot.pause()
            await pilot.click("#yes")
            await pilot.pause()
            assert manager.get_projects("acme") == []
            assert app.path == ("acme",)
            acme = app.query_one(Tree).root.children[0]
            assert len(acme.children) == 0

    asyncio.run(scenario())
