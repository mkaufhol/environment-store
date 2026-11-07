"""`StoresScreen`: every store and whether it is encrypted; enter opens one (PD 29).

`a` creates a store and `d` removes the selected one (D55), `x` exports stores to a file
(D56). `q` quits the app, here and on the variables screen; `escape` goes back from there.

An encrypted store is opened without asking with the key from `ENV_STORE_KEY_<STORE>` (D53),
else with the project file's key when it names one (PD 5); otherwise, or when that key does not
fit, the `UnlockScreen` asks for one.
"""

from typing import ClassVar, Final, override

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static
from textual.widgets.data_table import RowKey

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.tui.exporting import ExportFlow
from environment_store.tui.messages import notify_done, notify_error, notify_reminder
from environment_store.tui.screens.create import Created, CreateStoreScreen
from environment_store.tui.screens.remove import RemoveStoreScreen
from environment_store.tui.screens.unlock import UnlockScreen, describe_encryption
from environment_store.tui.screens.variables import VariablesScreen
from environment_store.tui.session import OpenedStore, StoreSession
from environment_store.tui.unlocking import open_without_asking

__all__ = ["EMPTY_HINT", "StoresScreen"]

EMPTY_HINT: Final = "No stores yet. Press a to create one"
"""Shown instead of an empty table."""


class _StoreTable(DataTable[Text]):
    """The stores table; its enter opens the selected store, and the footer says so."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "select_cursor", "Open")]


class StoresScreen(Screen[None]):
    """The list of stores, the TUI's first screen."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "create", "Add"),
        Binding("d", "remove", "Remove"),
        Binding("x", "export", "Export"),
        Binding("r", "reload", "Reload"),
        Binding("q", "app.quit", "Quit"),  # quits the app on every screen, not only here
    ]

    _session: StoreSession
    _stores: dict[RowKey, StoreInfo]

    def __init__(self, session: StoreSession) -> None:
        """Show the stores of a session.

        Args:
            session: The TUI's store session.
        """
        super().__init__()
        self._session = session
        self._stores = {}

    @override
    def compose(self) -> ComposeResult:
        """Show the table between header and footer."""
        yield Header()
        yield _StoreTable(id="stores", cursor_type="row")
        yield Static(EMPTY_HINT, id="empty", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        """Fill the table."""
        self.query_one(DataTable).add_columns("Store", "Encryption")
        self.action_reload()

    def action_reload(self) -> None:
        """List the stores again."""
        table = self.query_one(DataTable)
        table.clear()
        hint = self.query_one("#empty", Static)
        try:
            stores = self._session.stores()
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
            stores = []
            hint.display = False
        else:
            hint.display = not stores
        self._stores = {
            table.add_row(Text(info.name), Text(describe_encryption(info)), key=info.name): info
            for info in stores
        }

    def action_create(self) -> None:
        """Ask for a new store and create it (D55)."""
        existing = frozenset(info.name for info in self._stores.values())
        self.app.push_screen(CreateStoreScreen(self._session, existing=existing), self._created)

    def action_remove(self) -> None:
        """Remove the selected store after its name is typed (D55, D21)."""
        info = self._selected()
        if info is None:
            return
        name = info.name

        def answered(remove: bool | None) -> None:  # noqa: FBT001 - textual passes the result positionally
            if not remove:
                return
            try:
                self._session.delete_store(name)
            except EnvironmentStoreError as error:
                notify_error(self.app, error)
            else:
                notify_done(self.app, f"removed store {name!r}")
            self.action_reload()

        self.app.push_screen(RemoveStoreScreen(name), answered)

    def action_export(self) -> None:
        """Export stores to a file (D56)."""
        ExportFlow(self.app, self._session, list(self._stores.values())).start()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected store."""
        self.open_store(self._stores[event.row_key])

    def open_store(self, info: StoreInfo) -> None:
        """Open a store: directly, with its key variable or project key, or after asking.

        Args:
            info: The store's listing entry.
        """
        try:
            opened = open_without_asking(self.app, self._session, info)
        except EnvironmentStoreError as error:  # only a plaintext store fails here
            notify_error(self.app, error)
            return
        if opened is None:
            self.app.push_screen(UnlockScreen(self._session, info), self._show)
        else:
            self._show(opened)

    def _created(self, created: Created | None) -> None:
        if created is None:
            return
        self.action_reload()
        notify_done(self.app, f"created store {created.name!r}")
        if created.reminder is not None:
            notify_reminder(self.app, created.reminder)

    def _selected(self) -> StoreInfo | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self._stores[row_key]

    def _show(self, opened: OpenedStore | None) -> None:
        if opened is not None:
            self.app.push_screen(VariablesScreen(self._session, opened))
