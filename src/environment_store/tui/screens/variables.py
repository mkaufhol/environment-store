"""`VariablesScreen`: the variables of one store, values masked until shown (PD 29).

`v` shows or hides the values, `a` adds a variable, `e` or enter edits the selected one, `d`
deletes it after a confirmation, `r` reloads and `escape` goes back to the stores. A write that
conflicts with a change made elsewhere (D7) writes nothing and offers to reload.
"""

import json
from collections.abc import Callable
from typing import ClassVar, Final

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from environment_store.core.errors import ConcurrentModificationError, EnvironmentStoreError
from environment_store.tui.messages import notify_error
from environment_store.tui.screens.confirm import ConfirmScreen
from environment_store.tui.screens.edit import Edited, EditVariableScreen
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["MASK", "VariablesScreen", "shown_value"]

MASK: Final = "••••••••"
"""What a hidden value looks like; the same for every value, so it does not reveal the length."""


def shown_value(value: str) -> str:
    """Return a value for one table cell.

    Args:
        value: The value.

    Returns:
        The value if it is printable on one line, otherwise its JSON string form.
    """
    if value.isprintable():
        return value
    return json.dumps(value, ensure_ascii=False)


class VariablesScreen(Screen[None]):
    """The variables of one opened store."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "toggle_values", "Show / hide values"),
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("r", "reload", "Reload"),
        Binding("escape", "back", "Back"),
    ]

    _session: StoreSession
    _opened: OpenedStore
    _reveal: bool

    def __init__(self, session: StoreSession, opened: OpenedStore) -> None:
        """Show an opened store.

        Args:
            session: The TUI's store session.
            opened: The store with its variables and secret.
        """
        super().__init__()
        self._session = session
        self._opened = opened
        self._reveal = False

    @property
    def opened(self) -> OpenedStore:
        """The store as currently shown."""
        return self._opened

    def compose(self) -> ComposeResult:
        """Show the table between header and footer."""
        yield Header()
        yield DataTable(id="variables", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        """Fill the table."""
        self.sub_title = f"store {self._opened.name}"
        self.query_one(DataTable).add_columns("Variable", "Value")
        self._fill()

    def on_data_table_row_selected(self) -> None:
        """Enter on a row edits it."""
        self.action_edit()

    def action_toggle_values(self) -> None:
        """Show or hide the values."""
        self._reveal = not self._reveal
        self._fill()

    def action_add(self) -> None:
        """Ask for a new variable and add it."""
        dialog = EditVariableScreen(store=self._opened.name, existing=self._opened.variables)
        self.app.push_screen(dialog, self._add)

    def action_edit(self) -> None:
        """Ask for a new value of the selected variable."""
        name = self._selected()
        if name is None:
            return
        value = self._opened.variables[name]
        dialog = EditVariableScreen(store=self._opened.name, name=name, value=value)
        self.app.push_screen(dialog, self._replace)

    def action_delete(self) -> None:
        """Delete the selected variable after a confirmation."""
        name = self._selected()
        if name is None:
            return
        question = f"Delete variable {name!r} from store {self._opened.name!r}?"

        def answered(yes: bool | None) -> None:  # noqa: FBT001 - textual passes the result positionally
            if yes:
                self._write(lambda: self._session.delete(self._opened, name))

        self.app.push_screen(ConfirmScreen(question), answered)

    def action_reload(self) -> None:
        """Read the store again."""
        try:
            self._opened = self._session.reload(self._opened)
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
        self._fill()

    def action_back(self) -> None:
        """Go back to the stores; the key is forgotten with this screen (D3)."""
        self.dismiss(None)

    def _add(self, edited: Edited | None) -> None:
        if edited is not None:
            name, value = edited
            self._write(lambda: self._session.set(self._opened, name, value, overwrite=False))

    def _replace(self, edited: Edited | None) -> None:
        if edited is not None:
            name, value = edited
            self._write(lambda: self._session.set(self._opened, name, value, overwrite=True))

    def _write(self, change: Callable[[], OpenedStore]) -> None:
        try:
            self._opened = change()
        except ConcurrentModificationError as error:
            question = f"{error}. Reload store {self._opened.name!r} now?"

            def answered(yes: bool | None) -> None:  # noqa: FBT001 - textual passes the result positionally
                if yes:
                    self.action_reload()

            self.app.push_screen(ConfirmScreen(question), answered)
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
        self._fill()

    def _selected(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return row_key.value

    def _fill(self) -> None:
        table = self.query_one(DataTable)
        selected = self._selected()
        table.clear()
        for name, value in sorted(self._opened.variables.items()):
            cell = shown_value(value) if self._reveal else MASK
            # Text, not str: a str cell is parsed as markup, which would mangle '[...]'.
            table.add_row(Text(name), Text(cell), key=name)
        if selected is not None and selected in self._opened.variables:
            table.move_cursor(row=table.get_row_index(selected))
