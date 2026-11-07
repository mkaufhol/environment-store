"""`StoresScreen`: every store and whether it is encrypted; enter opens one (PD 29).

`q` quits the app, here and on the variables screen; `escape` goes back from there.

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
from environment_store.core.names import key_variable
from environment_store.tui.messages import message_for, notify_error, notify_problem
from environment_store.tui.screens.unlock import UnlockScreen, describe_encryption
from environment_store.tui.screens.variables import VariablesScreen
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["EMPTY_HINT", "StoresScreen"]

EMPTY_HINT: Final = "No stores yet. Create one with envs create-store NAME"
"""Shown instead of an empty table: the TUI does not create stores (D31)."""


class _StoreTable(DataTable[Text]):
    """The stores table; its enter opens the selected store, and the footer says so."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "select_cursor", "Open")]


class StoresScreen(Screen[None]):
    """The list of stores, the TUI's first screen."""

    BINDINGS: ClassVar[list[BindingType]] = [
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected store."""
        self.open_store(self._stores[event.row_key])

    def open_store(self, info: StoreInfo) -> None:
        """Open a store: directly, with its key variable or project key, or after asking.

        Args:
            info: The store's listing entry.
        """
        try:
            opened = self._open_without_asking(info)
        except EnvironmentStoreError as error:  # only a plaintext store fails here
            notify_error(self.app, error)
            return
        if opened is None:
            self.app.push_screen(UnlockScreen(self._session, info), self._show)
        else:
            self._show(opened)

    def _open_without_asking(self, info: StoreInfo) -> OpenedStore | None:
        name = info.name
        if not info.encrypted:
            return self._session.open(name)
        # D53: the key variable comes before the project key; when set, it alone is tried.
        try:
            secret = self._session.environment_secret(name)
            if secret is not None:
                return self._session.open(name, secret)
        except EnvironmentStoreError as error:
            self._notify_failed(key_variable(name), error)
            return None
        return self._open_with_project_key(name)

    def _open_with_project_key(self, name: str) -> OpenedStore | None:
        path = self._session.project_key(name)
        if path is None:
            return None
        try:
            return self._session.open(name, self._session.secret_from_file(name, path))
        except EnvironmentStoreError as error:
            self._notify_failed(f"the key file '{path}' from the project file", error)
            return None

    def _notify_failed(self, source: str, error: EnvironmentStoreError) -> None:
        # The user did not choose this key, so the message names it and where it came from.
        notify_problem(self.app, f"unlocking with {source} failed: {message_for(error)}")

    def _show(self, opened: OpenedStore | None) -> None:
        if opened is not None:
            self.app.push_screen(VariablesScreen(self._session, opened))
