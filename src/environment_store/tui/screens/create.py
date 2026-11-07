"""`CreateStoreScreen`: create a store with any encryption of `create-store` (D55, spec §6.3).

The name is validated as it is typed (D27, D40), and so are the other inputs, each with its
error below it. The store is created before the dialog closes, so a refused key keeps the
dialog and what was typed. A new passphrase or generated key file comes with the D45 reminder
that envs does not save it.
"""

from dataclasses import dataclass
from typing import ClassVar, Final, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, RadioButton, RadioSet, Static

from environment_store.core.errors import EnvironmentStoreError, ValidationError
from environment_store.core.secrets import Passphrase
from environment_store.core.validation import validate_store_name
from environment_store.tui.choices import GenerateKey, KeyFile, NewKey, TypedPassphrase
from environment_store.tui.messages import message_for, notify_error
from environment_store.tui.paths import PathInput, expand_path
from environment_store.tui.session import StoreSession

__all__ = ["CreateStoreScreen", "Created"]

_NONE: Final = "none"
_GENERATE: Final = "generate"
_KEYFILE: Final = "keyfile"
_PASSPHRASE: Final = "passphrase"  # noqa: S105 - a widget id, not a password
_FIELDS: Final = {
    _GENERATE: "#generate-fields",
    _KEYFILE: "#keyfile-fields",
    _PASSPHRASE: "#passphrase-fields",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Created:
    """A created store.

    Attributes:
        name: The store name.
        reminder: The D45 reminder for a new passphrase or generated key, or `None`.
    """

    name: str
    reminder: str | None


class _CreateInput(Input):
    """A text input whose enter creates the store, and says so in the footer."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Create")]


class _CreatePathInput(PathInput):
    """A path input (D57) whose enter creates the store."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Create")]


def _error_line(widget_id: str) -> Static:
    line = Static("", id=widget_id, classes="error", markup=False)
    line.display = False
    return line


class CreateStoreScreen(ModalScreen[Created | None]):
    """Ask for a name and an encryption; dismisses with the created store, or `None`."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "create", "Create"),
        Binding("escape", "cancel", "Cancel"),
    ]

    _session: StoreSession
    _existing: frozenset[str]
    _suggested_path: str

    def __init__(self, session: StoreSession, *, existing: frozenset[str]) -> None:
        """Create the dialog.

        Args:
            session: The TUI's store session.
            existing: The names of the listed stores; they are refused as you type.
        """
        super().__init__()
        self._session = session
        self._existing = existing
        self._suggested_path = ""

    @override
    def compose(self) -> ComposeResult:
        """Show the name, the encryption choice, its inputs and the buttons."""
        with Vertical(classes="dialog"):
            yield Label("Create a store", markup=False)
            yield _CreateInput(placeholder="Store name, e.g. base_conf", id="name")
            yield _error_line("name-error")
            yield Label("Encryption", markup=False)
            with RadioSet(id="encryption"):
                yield RadioButton("None", value=True, id=_NONE)
                yield RadioButton("New key file (generated)", id=_GENERATE)
                yield RadioButton("Existing key file", id=_KEYFILE)
                yield RadioButton("Passphrase", id=_PASSPHRASE)
            with Vertical(id="generate-fields", classes="fields"):
                yield _CreatePathInput(
                    placeholder="Where to write the new key file", id="generate-path"
                )
                yield _error_line("generate-error")
            with Vertical(id="keyfile-fields", classes="fields"):
                yield _CreatePathInput(placeholder="Key file, e.g. ~/.keys/a.key", id="key-path")
                yield _error_line("key-error")
            with Vertical(id="passphrase-fields", classes="fields"):
                yield _CreateInput(placeholder="Passphrase", password=True, id="passphrase-input")
                yield _CreateInput(placeholder="Passphrase again", password=True, id="repeat")
                yield _error_line("passphrase-error")
            with Horizontal(classes="buttons"):
                yield Button("Create (ctrl+s)", id="create", variant="primary")
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Hide the key inputs and focus the name."""
        self._show_fields(_NONE)
        self.query_one("#name", Input).focus()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Show the inputs of the chosen encryption."""
        self._show_fields(event.pressed.id or _NONE)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Check what was typed and show or clear the input's error."""
        match event.input.id:
            case "name":
                self._show_error("#name-error", self._name_problem(event.value, typing=True))
                self._suggest_path(event.value)
            case "generate-path":
                self._show_error(
                    "#generate-error", self._generate_problem(event.value, typing=True)
                )
            case "key-path":
                self._show_error("#key-error", "")
            case _:
                self._show_error("#passphrase-error", self._passphrase_problem(typing=True))

    def on_input_submitted(self) -> None:
        """Enter in any input creates the store."""
        self.action_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Create or cancel."""
        if event.button.id == "create":
            self.action_create()
        else:
            self.action_cancel()

    def action_create(self) -> None:
        """Check every input, create the store, then close with it."""
        name = self.query_one("#name", Input).value
        problem = self._name_problem(name, typing=False)
        self._show_error("#name-error", problem)
        checked = self._checked_key(name)
        if problem or checked is None:
            return
        key, reminder = checked
        try:
            self._session.create_store(name, key)
        except EnvironmentStoreError as error:
            notify_error(self.app, error)
            return
        self.dismiss(Created(name=name, reminder=reminder))

    def action_cancel(self) -> None:
        """Close without creating a store."""
        self.dismiss(None)

    def _chosen(self) -> str:
        pressed = self.query_one(RadioSet).pressed_button
        return _NONE if pressed is None or pressed.id is None else pressed.id

    def _show_fields(self, chosen: str) -> None:
        for choice, selector in _FIELDS.items():
            self.query_one(selector).display = choice == chosen
        if chosen == _GENERATE:
            self._suggest_path(self.query_one("#name", Input).value)

    def _show_error(self, selector: str, problem: str) -> None:
        line = self.query_one(selector, Static)
        line.update(problem)
        line.display = bool(problem)

    def _name_problem(self, name: str, *, typing: bool) -> str:
        if not name:
            return "" if typing else "enter a store name"
        try:
            validate_store_name(name)
        except ValidationError as error:
            return message_for(error)
        return f"store {name!r} exists already" if name in self._existing else ""

    def _suggest_path(self, name: str) -> None:
        # The suggestion follows the name until the user types a path of their own.
        path = self.query_one("#generate-path", Input)
        if path.value != self._suggested_path:
            return
        self._suggested_path = f"./{name}.key" if name else ""
        path.value = self._suggested_path

    def _generate_problem(self, text: str, *, typing: bool) -> str:
        if not text.strip():
            return "" if typing else "enter the path of the new key file"
        try:
            path = expand_path(text, what="key file")
        except ValidationError as error:
            return message_for(error)
        if path.exists() or path.is_symlink():
            return (
                f"'{text.strip()}' exists already; a key file is never overwritten: choose "
                "another path"
            )
        return ""

    def _passphrase_problem(self, *, typing: bool) -> str:
        first = self.query_one("#passphrase-input", Input).value
        second = self.query_one("#repeat", Input).value
        if not first:
            return "" if typing else "enter a passphrase"
        if second != first and (second or not typing):
            return "the passphrases do not match"
        return ""

    def _checked_key(self, name: str) -> tuple[NewKey | None, str | None] | None:
        """Return the chosen key with its D45 reminder, or `None` after showing a problem."""
        tail = f"keep it, or store {name!r} cannot be read again"
        match self._chosen():
            case "passphrase":
                problem = self._passphrase_problem(typing=False)
                self._show_error("#passphrase-error", problem)
                if problem:
                    return None
                text = self.query_one("#passphrase-input", Input).value
                return TypedPassphrase(Passphrase(text=text)), (
                    f"envs does not save this passphrase; {tail}"
                )
            case "generate":
                text = self.query_one("#generate-path", Input).value
                problem = self._generate_problem(text, typing=False)
                self._show_error("#generate-error", problem)
                if problem:
                    return None
                return GenerateKey(expand_path(text, what="key file")), (
                    f"the new key was written to '{text.strip()}'; envs does not save it anywhere "
                    f"else: {tail}"
                )
            case "keyfile":
                text = self.query_one("#key-path", Input).value
                problem = _key_file_problem(text)
                self._show_error("#key-error", problem)
                return None if problem else (KeyFile(expand_path(text, what="key file")), None)
            case _:
                return None, None


def _key_file_problem(text: str) -> str:
    if not text.strip():
        return "enter the path of the key file"
    try:
        expand_path(text, what="key file")
    except ValidationError as error:
        return message_for(error)
    return ""
