"""`EditVariableScreen`: add a variable or edit a value, with a multi-line editor (PD 29).

The name and the value are validated here, so a typo keeps the dialog and what was typed; the
write itself happens in the variables screen.
"""

from collections.abc import Collection
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, TextArea

from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_value, validate_variable_name
from environment_store.tui.messages import notify_problem

__all__ = ["EditVariableScreen", "Edited"]

type Edited = tuple[str, str]
"""The name and the new value."""


class EditVariableScreen(ModalScreen[Edited | None]):
    """Ask for a name and a value; dismisses with them, or `None` when cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    _store: str
    _name: str | None
    _value: str
    _existing: frozenset[str]

    def __init__(
        self,
        *,
        store: str,
        name: str | None = None,
        value: str = "",
        existing: Collection[str] = (),
    ) -> None:
        """Create the dialog.

        Args:
            store: The store the variable belongs to (for the title).
            name: The variable to edit; `None` to add a new one.
            value: The current value.
            existing: The names already in the store; adding one of them is refused.
        """
        super().__init__()
        self._store = store
        self._name = name
        self._value = value
        self._existing = frozenset(existing)

    def compose(self) -> ComposeResult:
        """Show the name input, the value editor and the buttons."""
        title = (
            f"Add a variable to store {self._store!r}"
            if self._name is None
            else f"Edit {self._name!r} in store {self._store!r}"
        )
        with Vertical(classes="dialog"):
            yield Label(title, markup=False)
            yield Input(
                value=self._name or "",
                placeholder="NAME",
                id="name",
                disabled=self._name is not None,
            )
            yield TextArea(self._value, id="value")
            with Horizontal(classes="buttons"):
                yield Button("Save (ctrl+s)", id="save", variant="primary")
                yield Button("Cancel (esc)", id="cancel")

    def on_mount(self) -> None:
        """Focus the first thing to type in."""
        target = "#name" if self._name is None else "#value"
        self.query_one(target).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Save or cancel."""
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()

    def on_input_submitted(self) -> None:
        """Enter in the name input moves on to the value."""
        self.query_one("#value", TextArea).focus()

    def action_save(self) -> None:
        """Check the name and the value, then close with them."""
        name = self._name if self._name is not None else self.query_one("#name", Input).value
        value = self.query_one("#value", TextArea).text
        try:
            validate_variable_name(name)
            validate_value(value, variable=name)
        except ValidationError as error:
            notify_problem(self.app, str(error))
            return
        if self._name is None and name in self._existing:
            notify_problem(
                self.app, f"variable {name!r} exists already in store {self._store!r}: edit it"
            )
            return
        self.dismiss((name, value))

    def action_cancel(self) -> None:
        """Close without a change."""
        self.dismiss(None)
