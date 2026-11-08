"""`RemoveStoreScreen`: remove a store after its name is typed exactly (D55, D21).

Removing deletes the store with all its variables and cannot be undone, so a yes is not
enough: the Remove action works only while the typed text equals the store name. Like
`rm-store` it needs no key, also for an encrypted store (D21).
"""

from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label

from environment_store.tui.messages import notify_problem

__all__ = ["RemoveStoreScreen"]


class _NameInput(Input):
    """The input for the store name; its enter removes, and the footer says so."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Remove")]


class RemoveStoreScreen(ModalScreen[bool]):
    """Ask for the store's name; dismisses with `True` to remove it, `False` otherwise."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    _name: str

    def __init__(self, name: str) -> None:
        """Create the dialog.

        Args:
            name: The store to remove.
        """
        super().__init__()
        self._name = name

    @override
    def compose(self) -> ComposeResult:
        """Show the warning, the name input and the buttons."""
        with Vertical(classes="dialog"):
            yield Label(
                f"Remove store {self._name!r}? The store and all its variables are deleted. "
                "This cannot be undone.",
                markup=False,
            )
            yield Label(f"Type {self._name} to confirm:", markup=False)
            yield _NameInput(placeholder=self._name, id="confirm")
            with Horizontal(classes="buttons"):
                yield Button("Remove", id="remove", variant="error", disabled=True)
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the name input."""
        self.query_one("#confirm", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Enable Remove only while the exact name is typed."""
        self.query_one("#remove", Button).disabled = event.value != self._name

    def on_input_submitted(self) -> None:
        """Enter removes, if the name matches."""
        self.action_remove()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Remove or cancel."""
        if event.button.id == "remove":
            self.action_remove()
        else:
            self.action_cancel()

    def action_remove(self) -> None:
        """Close with `True` if the typed text is exactly the store name."""
        if self.query_one("#confirm", Input).value != self._name:
            notify_problem(self.app, f"type the store name {self._name!r} exactly to remove it")
            return
        self.dismiss(True)  # noqa: FBT003 - the dialog's result

    def action_cancel(self) -> None:
        """Close without removing."""
        self.dismiss(False)  # noqa: FBT003 - the dialog's result
