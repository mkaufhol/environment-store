"""`StoresScreen`: every store and whether it is encrypted; enter opens one (PD 29).

An encrypted store is opened with the project file's key when it names one (PD 5), without
asking; otherwise, or when that key does not fit, the `UnlockScreen` asks for one.
"""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header
from textual.widgets.data_table import RowKey

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.tui.messages import notify_error
from environment_store.tui.screens.unlock import UnlockScreen, describe_encryption
from environment_store.tui.screens.variables import VariablesScreen
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["StoresScreen"]


class StoresScreen(Screen[None]):
    """The list of stores, the TUI's first screen."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "reload", "Reload"),
        Binding("q", "app.quit", "Quit"),
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

    def compose(self) -> ComposeResult:
        """Show the table between header and footer."""
        yield Header()
        yield DataTable(id="stores", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        """Fill the table."""
        self.query_one(DataTable).add_columns("Store", "Encryption")
        self.action_reload()

    def action_reload(self) -> None:
        """List the stores again."""
        table = self.query_one(DataTable)
        table.clear()
        try:
            stores = self._session.stores()
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
            stores = []
        self._stores = {
            table.add_row(Text(info.name), Text(describe_encryption(info)), key=info.name): info
            for info in stores
        }

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected store."""
        self.open_store(self._stores[event.row_key])

    def open_store(self, info: StoreInfo) -> None:
        """Open a store: directly, with the project key, or after asking for a key.

        Args:
            info: The store's listing entry.
        """
        try:
            opened = self._open_without_asking(info)
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
            if not info.encrypted:
                return
            opened = None
        if opened is None:
            self.app.push_screen(UnlockScreen(self._session, info), self._show)
        else:
            self._show(opened)

    def _open_without_asking(self, info: StoreInfo) -> OpenedStore | None:
        if not info.encrypted:
            return self._session.open(info.name)
        path = self._session.project_key(info.name)
        if path is None:
            return None
        return self._session.open(info.name, self._session.secret_from_file(info.name, path))

    def _show(self, opened: OpenedStore | None) -> None:
        if opened is not None:
            self.app.push_screen(VariablesScreen(self._session, opened))
