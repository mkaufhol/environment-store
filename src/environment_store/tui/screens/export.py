"""The export dialogs: stores in order, options, output path.

1. `ExportStoresScreen`: choosing a store appends it to the load order and shows its position;
   unchoosing one renumbers the rest.
2. `ExportOptionsScreen`: the format, `--nested` and `--first-wins`; the merge order starts
   from the configured one.
3. `ExportPathScreen`: the output path (with path completion) and the format again,
   preselected from the path's extension as it is typed, like `-t`. An existing file is
   replaced only after a confirmation (`--force`).
"""

import dataclasses
from collections.abc import Sequence
from typing import ClassVar, Final, override

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Input,
    Label,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)
from textual.widgets.selection_list import Selection

from environment_store.core.errors import ValidationError
from environment_store.core.models import StoreInfo
from environment_store.formats.infer import Format, infer_format
from environment_store.tui.choices import ExportOptions, ExportTarget
from environment_store.tui.messages import message_for, notify_problem
from environment_store.tui.paths import PathInput, expand_path
from environment_store.tui.screens.confirm import ConfirmScreen
from environment_store.tui.screens.unlock import describe_encryption

__all__ = ["ExportOptionsScreen", "ExportPathScreen", "ExportStoresScreen"]

_FORMAT_LABELS: Final = {Format.DOTENV: "dotenv", Format.JSON: "JSON", Format.TOML: "TOML"}


def _format_buttons(chosen: Format) -> list[RadioButton]:
    return [
        RadioButton(label, value=fmt is chosen, id=f"fmt-{fmt.value}")
        for fmt, label in _FORMAT_LABELS.items()
    ]


def _chosen_format(formats: RadioSet) -> Format:
    pressed = formats.pressed_button
    return Format.DOTENV if pressed is None or pressed.id is None else Format(pressed.id[4:])


class _StoreChoice(SelectionList[str]):
    """The stores to export; space or enter chooses one, and the footer says so."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("space", "select", "Choose")]


class ExportStoresScreen(ModalScreen[list[str] | None]):
    """Choose stores in load order; dismisses with their names, or `None` when cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "next", "Next"),
        Binding("escape", "cancel", "Cancel"),
    ]

    _stores: tuple[StoreInfo, ...]
    _order: list[str]

    def __init__(self, stores: Sequence[StoreInfo]) -> None:
        """Create the dialog.

        Args:
            stores: The stores that can be exported.
        """
        super().__init__()
        self._stores = tuple(stores)
        self._order = []

    @property
    def order(self) -> list[str]:
        """The chosen stores in load order."""
        return list(self._order)

    @override
    def compose(self) -> ComposeResult:
        """Show the stores and the buttons."""
        with Vertical(classes="dialog"):
            yield Label(
                "Export, step 1 of 3: choose the stores in load order (later stores win unless "
                "first wins is chosen)",
                markup=False,
            )
            yield _StoreChoice(
                *(Selection(self._prompt(info), info.name, id=info.name) for info in self._stores),
                id="stores",
            )
            with Horizontal(classes="buttons"):
                yield Button("Next (ctrl+s)", id="next", variant="primary")
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the store list."""
        self.query_one(SelectionList).focus()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        """Keep the load order: new stores at the end, removed ones out, then renumber."""
        selected = event.selection_list.selected
        kept = [name for name in self._order if name in selected]
        self._order = kept + [name for name in selected if name not in kept]
        choice = self.query_one(SelectionList)
        for info in self._stores:
            choice.replace_option_prompt(info.name, self._prompt(info))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Go on or cancel."""
        if event.button.id == "next":
            self.action_next()
        else:
            self.action_cancel()

    def action_next(self) -> None:
        """Close with the chosen stores, if there is one."""
        if not self._order:
            notify_problem(self.app, "choose at least one store to export")
            return
        self.dismiss(self.order)

    def action_cancel(self) -> None:
        """Close without exporting."""
        self.dismiss(None)

    def _prompt(self, info: StoreInfo) -> Text:
        position = self._order.index(info.name) + 1 if info.name in self._order else None
        number = "  " if position is None else f"{position:>2}"
        return Text(f"{number}  {info.name}  ({describe_encryption(info)})")


class ExportOptionsScreen(ModalScreen[ExportOptions | None]):
    """Choose format, nested and merge order; dismisses with them, or `None`."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "next", "Next"),
        Binding("escape", "cancel", "Cancel"),
    ]

    _stores: tuple[str, ...]
    _first_wins: bool

    def __init__(self, stores: Sequence[str], *, first_wins: bool) -> None:
        """Create the dialog.

        Args:
            stores: The chosen stores in load order.
            first_wins: The configured merge order, the default of the checkbox.
        """
        super().__init__()
        self._stores = tuple(stores)
        self._first_wins = first_wins

    @override
    def compose(self) -> ComposeResult:
        """Show the options and the buttons."""
        with Vertical(classes="dialog"):
            yield Label(f"Export, step 2 of 3: options for {', '.join(self._stores)}", markup=False)
            yield Label("Format", markup=False)
            with RadioSet(id="format"):
                yield from _format_buttons(Format.DOTENV)
            yield Checkbox("Nested: one namespace per store instead of merging", id="nested")
            yield Checkbox(
                "First wins: the first store wins instead of the last",
                value=self._first_wins,
                id="first-wins",
            )
            with Horizontal(classes="buttons"):
                yield Button("Next (ctrl+s)", id="next", variant="primary")
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the format choice."""
        self.query_one(RadioSet).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Go on or cancel."""
        if event.button.id == "next":
            self.action_next()
        else:
            self.action_cancel()

    def action_next(self) -> None:
        """Close with the options."""
        self.dismiss(
            ExportOptions(
                fmt=_chosen_format(self.query_one(RadioSet)),
                nested=self.query_one("#nested", Checkbox).value,
                first_wins=self.query_one("#first-wins", Checkbox).value,
            )
        )

    def action_cancel(self) -> None:
        """Close without exporting."""
        self.dismiss(None)


class _ExportPathInput(PathInput):
    """The output path; its enter exports, and the footer says so."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "submit", "Export")]


class ExportPathScreen(ModalScreen[ExportTarget | None]):
    """Ask for the output path; dismisses with the target, or `None` when cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "export", "Export"),
        Binding("escape", "cancel", "Cancel"),
    ]

    _options: ExportOptions
    _inferred: Format | None

    def __init__(self, options: ExportOptions) -> None:
        """Create the dialog.

        Args:
            options: The options of step 2.
        """
        super().__init__()
        self._options = options
        self._inferred = None

    @override
    def compose(self) -> ComposeResult:
        """Show the path input, the format and the buttons."""
        with Vertical(classes="dialog"):
            yield Label("Export, step 3 of 3: the output file (mode 0600)", markup=False)
            yield _ExportPathInput(placeholder="e.g. .env, config.json, settings.toml", id="path")
            yield Static("", id="path-error", classes="error", markup=False)
            yield Label("Format (follows the file extension)", markup=False)
            with RadioSet(id="format"):
                yield from _format_buttons(self._options.fmt)
            with Horizontal(classes="buttons"):
                yield Button("Export (ctrl+s)", id="export", variant="primary")
                yield Button("Cancel (esc)", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Hide the error line and focus the path input."""
        self.query_one("#path-error").display = False
        self.query_one("#path", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Preselect the format a newly typed extension names and clear the error."""
        self._show_error("")
        inferred = infer_format(event.value.strip())
        if inferred is not None and inferred is not self._inferred:
            self.query_one(f"#fmt-{inferred.value}", RadioButton).value = True
        self._inferred = inferred

    def on_input_submitted(self) -> None:
        """Enter exports."""
        self.action_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Export or cancel."""
        if event.button.id == "export":
            self.action_export()
        else:
            self.action_cancel()

    def action_export(self) -> None:
        """Check the path; an existing file needs a confirmation before closing."""
        text = self.query_one("#path", Input).value.strip()
        if not text:
            self._show_error("enter the path of the output file")
            return
        try:
            path = expand_path(text, what="output file")
        except ValidationError as error:
            self._show_error(message_for(error))
            return
        if path.is_dir():
            self._show_error(f"'{text}' is a directory: enter a file path")
            return
        options = dataclasses.replace(self._options, fmt=_chosen_format(self.query_one(RadioSet)))
        if not (path.exists() or path.is_symlink()):
            self.dismiss(ExportTarget(path=path, options=options, replace=False))
            return

        def answered(yes: bool | None) -> None:  # noqa: FBT001 - textual passes the result positionally
            if yes:
                self.dismiss(ExportTarget(path=path, options=options, replace=True))

        self.app.push_screen(ConfirmScreen(f"File '{text}' exists already. Replace it?"), answered)

    def action_cancel(self) -> None:
        """Close without exporting."""
        self.dismiss(None)

    def _show_error(self, problem: str) -> None:
        line = self.query_one("#path-error", Static)
        line.update(problem)
        line.display = bool(problem)
