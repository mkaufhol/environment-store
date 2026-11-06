"""`UnlockScreen`: ask for the key of an encrypted store (D3, PD 29).

The user types the path of a key or passphrase file, or the passphrase itself (hidden). The
store is read with it before the dialog closes, so a wrong key keeps the store locked and the
dialog open; the key is never remembered beyond the shown store (D3).
"""

from pathlib import Path
from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import Secret
from environment_store.tui.messages import notify_error, notify_problem
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["UnlockScreen", "describe_encryption"]


def describe_encryption(info: StoreInfo) -> str:
    """Describe whether and how a store is encrypted, e.g. `encrypted (passphrase)`.

    Args:
        info: The store's listing entry.

    Returns:
        `plain`, or `encrypted (<key mode>)`.
    """
    if not info.encrypted:
        return "plain"
    mode = "unknown key mode" if info.key_mode is None else info.key_mode.value
    return f"encrypted ({mode})"


class UnlockScreen(ModalScreen[OpenedStore | None]):
    """Ask for a key; dismisses with the opened store, or `None` when cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    _session: StoreSession
    _info: StoreInfo

    def __init__(self, session: StoreSession, info: StoreInfo) -> None:
        """Create the dialog.

        Args:
            session: The TUI's store session.
            info: The encrypted store.
        """
        super().__init__()
        self._session = session
        self._info = info

    @override
    def compose(self) -> ComposeResult:
        """Show the two inputs and the buttons."""
        with Vertical(classes="dialog"):
            yield Label(
                f"Unlock store {self._info.name!r}, {describe_encryption(self._info)}",
                markup=False,
            )
            yield Input(placeholder="Key or passphrase file, e.g. ~/.keys/a.key", id="path")
            yield Input(placeholder="or the passphrase", password=True, id="passphrase")
            with Horizontal(classes="buttons"):
                yield Button("Unlock", id="unlock", variant="primary")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self) -> None:
        """Focus the path input."""
        self.query_one("#path", Input).focus()

    def on_input_submitted(self) -> None:
        """Enter in either input unlocks."""
        self.action_unlock()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Unlock or cancel."""
        if event.button.id == "unlock":
            self.action_unlock()
        else:
            self.action_cancel()

    def action_unlock(self) -> None:
        """Read the store with the given key; on success close with it."""
        passphrase = self.query_one("#passphrase", Input)
        path = self.query_one("#path", Input).value.strip()
        if bool(path) == bool(passphrase.value):
            notify_problem(self.app, "enter either a key or passphrase file, or the passphrase")
            return
        name = self._info.name
        try:
            secret = self._secret(path, passphrase.value)
            opened = self._session.open(name, secret)
        except EnvironmentStoreError as error:
            passphrase.value = ""
            notify_error(self.app, error)
            return
        self.dismiss(opened)

    def action_cancel(self) -> None:
        """Close without unlocking."""
        self.dismiss(None)

    def _secret(self, path: str, passphrase: str) -> Secret:
        name = self._info.name
        if path:
            return self._session.secret_from_file(name, Path(path))
        return self._session.secret_from_text(name, passphrase)
