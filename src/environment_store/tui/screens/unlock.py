"""`UnlockScreen`: ask for the key of an encrypted store.

The user types the path of a key or passphrase file (with path completion), or the key
text or passphrase itself into a hidden field; both are worded for the store's key mode. Key
text typed into the visible path field is refused and wiped. The store is read with the secret
before the dialog closes, so a wrong key keeps the store locked and the dialog open; the key is
never remembered beyond the shown store.
"""

from dataclasses import dataclass
from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import KeyMode, StoreInfo
from environment_store.core.secrets import Secret
from environment_store.library.keys import parse_key_text
from environment_store.tui.messages import message_for, notify_problem
from environment_store.tui.paths import PathInput, expand_path
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["UnlockScreen", "UnlockWording", "describe_encryption", "unlock_wording"]


def describe_encryption(info: StoreInfo) -> str:
    """Describe whether and how a store is encrypted, e.g. `encrypted (passphrase)`.

    Args:
        info: The store's listing entry.

    Returns:
        `plain`, `encrypted (<key mode>)`, or `encrypted (unknown)` for cipher metadata this
        version does not know, worded like the CLI's `ls-store`.
    """
    if not info.encrypted:
        return "plain"
    mode = "unknown" if info.key_mode is None else info.key_mode.value
    return f"encrypted ({mode})"


@dataclass(frozen=True, slots=True, kw_only=True)
class UnlockWording:
    """What the Unlock dialog calls its fields and inputs for one key mode.

    Attributes:
        path_placeholder: The path field's placeholder.
        hidden_placeholder: The hidden field's placeholder.
        typed_source: How a failure names the hidden field's text.
        missing: The message when neither or both fields are filled in.
    """

    path_placeholder: str
    hidden_placeholder: str
    typed_source: str
    missing: str


_WORDING: dict[KeyMode | None, UnlockWording] = {
    KeyMode.KEYFILE: UnlockWording(
        path_placeholder="Key file path, e.g. ~/.keys/a.key",
        hidden_placeholder="or paste the key itself",
        typed_source="the pasted key",
        missing="enter either the key file path or the key itself",
    ),
    KeyMode.PASSPHRASE: UnlockWording(
        path_placeholder="Passphrase file path, e.g. ~/.keys/a.pass",
        hidden_placeholder="or type the passphrase",
        typed_source="the typed passphrase",
        missing="enter either a passphrase file path or the passphrase",
    ),
    None: UnlockWording(
        path_placeholder="Key or passphrase file path",
        hidden_placeholder="or paste the key or type the passphrase",
        typed_source="the typed key or passphrase",
        missing="enter either a key or passphrase file path, or the key or passphrase itself",
    ),
}

_KEY_IN_PATH: str = "that is a key, not a file path: paste it into the hidden field below"


def unlock_wording(mode: KeyMode | None) -> UnlockWording:
    """The Unlock dialog's wording for a store's key mode.

    Args:
        mode: The store's key mode; `None` for cipher metadata this version does not know.

    Returns:
        The placeholders and messages for that mode.
    """
    return _WORDING[mode]


def _is_key_text(text: str) -> bool:
    try:
        parse_key_text(text)
    except EnvironmentStoreError:
        return False
    return True


class _KeyInput(Input):
    """An input whose enter unlocks, and says so in the footer."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Unlock")]


class _KeyPathInput(PathInput):
    """The key file path (with path completion); its enter unlocks."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Unlock")]


class UnlockScreen(ModalScreen[OpenedStore | None]):
    """Ask for a key; dismisses with the opened store, or `None` when cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    _session: StoreSession
    _info: StoreInfo
    _wording: UnlockWording

    def __init__(self, session: StoreSession, info: StoreInfo) -> None:
        """Create the dialog.

        Args:
            session: The TUI's store session.
            info: The encrypted store.
        """
        super().__init__()
        self._session = session
        self._info = info
        self._wording = unlock_wording(info.key_mode)

    @override
    def compose(self) -> ComposeResult:
        """Show the two inputs and the buttons."""
        with Vertical(classes="dialog"):
            yield Label(
                f"Unlock store {self._info.name!r}, {describe_encryption(self._info)}",
                markup=False,
            )
            yield _KeyPathInput(placeholder=self._wording.path_placeholder, id="path")
            yield _KeyInput(
                placeholder=self._wording.hidden_placeholder, password=True, id="passphrase"
            )
            with Horizontal(classes="buttons"):
                yield Button("Unlock", id="unlock", variant="primary")
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

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
        """Read the store with the given key; on success close with it.

        A failure names the input it came from: the key file path, or the hidden field's key or
        passphrase. Key text in the visible path field is wiped and never used.
        """
        passphrase = self.query_one("#passphrase", Input)
        path_input = self.query_one("#path", Input)
        path = path_input.value.strip()
        if path and _is_key_text(path):
            path_input.value = ""
            notify_problem(self.app, _KEY_IN_PATH)
            return
        if bool(path) == bool(passphrase.value):
            notify_problem(self.app, self._wording.missing)
            return
        name = self._info.name
        try:
            secret = self._secret(path, passphrase.value)
            opened = self._session.open(name, secret)
        except EnvironmentStoreError as error:
            passphrase.value = ""
            source = f"the key file '{path}'" if path else self._wording.typed_source
            notify_problem(self.app, f"unlocking with {source} failed: {message_for(error)}")
            return
        self.dismiss(opened)

    def action_cancel(self) -> None:
        """Close without unlocking."""
        self.dismiss(None)

    def _secret(self, path: str, passphrase: str) -> Secret:
        name = self._info.name
        if path:
            return self._session.secret_from_file(name, expand_path(path, what="key file"))
        return self._session.secret_from_text(name, passphrase)
