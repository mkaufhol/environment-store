"""`ConfirmScreen`: a yes / no question as a modal dialog."""

from typing import ClassVar, override

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

__all__ = ["ConfirmScreen"]


class ConfirmScreen(ModalScreen[bool]):
    """Ask a question; dismisses with `True` for yes and `False` for no or escape.

    `No` has the focus, so enter, the key that opens and edits elsewhere, never answers yes.
    """

    AUTO_FOCUS: ClassVar[str | None] = "#no"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n", "answer(False)", "No"),
        Binding("escape", "answer(False)", "No"),
    ]

    _question: str

    def __init__(self, question: str) -> None:
        """Create the dialog.

        Args:
            question: The question, e.g. "Delete variable 'X'?".
        """
        super().__init__()
        self._question = question

    @override
    def compose(self) -> ComposeResult:
        """Show the question and the two answers."""
        with Vertical(classes="dialog"):
            yield Label(self._question, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Yes", id="yes", variant="error")
                yield Button("No", id="no", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Answer with the pressed button."""
        self.action_answer(answer=event.button.id == "yes")

    def action_answer(self, answer: bool) -> None:  # noqa: FBT001 - textual passes action arguments positionally
        """Close the dialog with the answer.

        Args:
            answer: `True` for yes.
        """
        self.dismiss(answer)
