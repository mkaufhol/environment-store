from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static, Tree

from environment_store.core import EnvironmentStoreManager
from environment_store.core.hierarchy import (
    LEVELS,
    Path,
    child_kind,
    describe,
    level_kind,
    to_kwargs,
)
from environment_store.core.schemas import Variable


class HierarchyTree(Tree[Path]):
    """The level tree. Arrow keys and vim keys do the same: up/down (k/j), collapse/parent (h/left),
    expand/child/switch to the variables (l/right)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("h,left", "collapse_or_parent", "Collapse", show=False),
        Binding("l,right", "expand_or_descend", "Expand", show=False),
    ]

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded and not node.is_root:
            node.collapse()
        elif node.parent is not None:
            self.move_cursor(node.parent)

    def action_expand_or_descend(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
        elif node.is_expanded and node.children:
            self.action_cursor_down()
        else:
            self.app.query_one("#vars", DataTable).focus()


class VariableTable(DataTable):
    """The variables table. j/k move like up/down, h/left goes back to the tree."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("h,left", "focus_tree", "Tree", show=False),
    ]

    def action_focus_tree(self) -> None:
        self.app.query_one("#tree", Tree).focus()


class VariableForm(ModalScreen[tuple[str, str] | None]):
    """Prompt for a variable name and value. Returns ``(name, value)`` or ``None``."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, name: str = "", value: str = "") -> None:
        super().__init__()
        self._name, self._value = name, value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Edit variable" if self._name else "Add variable")
            yield Input(self._name, placeholder="NAME", id="name", disabled=bool(self._name))
            yield Input(self._value, placeholder="value", id="value")
            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value" if self._name else "#name", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def save(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.notify("Name must not be empty", severity="error")
            return
        self.dismiss((name, self.query_one("#value", Input).value))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class NewLevelForm(ModalScreen[tuple[str, str, str] | None]):
    """Prompt for a child level name and its first variable. Returns ``(level, name, value)``."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, kind: str, parent: str) -> None:
        super().__init__()
        self._kind, self._where = kind, parent

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"New {self._kind} under {self._where}")
            yield Label("A level exists once it holds a variable, so add its first one.")
            yield Input(placeholder=f"{self._kind} name", id="level")
            yield Input(placeholder="VARIABLE_NAME", id="name")
            yield Input(placeholder="value", id="value")
            with Horizontal(id="buttons"):
                yield Button("Create", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#level", Input).focus()

    @on(Input.Submitted)
    @on(Button.Pressed, "#save")
    def save(self) -> None:
        level = self.query_one("#level", Input).value.strip()
        name = self.query_one("#name", Input).value.strip()
        if not level or not name:
            self.notify("Level name and variable name must not be empty", severity="error")
            return
        self.dismiss((level, name, self.query_one("#value", Input).value))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDeleteLevel(ModalScreen[str | None]):
    """Warn about deleting a level and require typing its name to confirm."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self, kind: str, name: str, where: str, variables: int, sub_levels: int
    ) -> None:
        super().__init__()
        self._kind, self._level_name, self._where = kind, name, where
        self._variables, self._sub_levels = variables, sub_levels

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"Delete {self._kind} '{self._level_name}'?", id="warning-title")
            yield Label(
                f"This permanently deletes {self._where}, {self._sub_levels} level(s) below it "
                f"and {self._variables} variable(s). This cannot be undone."
            )
            yield Label(f"Type '{self._level_name}' to confirm:")
            yield Input(placeholder=self._level_name, id="confirm")
            with Horizontal(id="buttons"):
                yield Button("Delete", variant="error", id="yes", disabled=True)
                yield Button("Cancel", id="no")

    def on_mount(self) -> None:
        self.query_one("#confirm", Input).focus()

    @on(Input.Changed, "#confirm")
    def confirm_changed(self, event: Input.Changed) -> None:
        self.query_one("#yes", Button).disabled = event.value != self._level_name

    @on(Input.Submitted, "#confirm")
    def confirm_submitted(self, event: Input.Submitted) -> None:
        if event.value == self._level_name:
            self.dismiss(event.value)

    @on(Button.Pressed, "#yes")
    def yes(self) -> None:
        self.dismiss(self.query_one("#confirm", Input).value)

    @on(Button.Pressed, "#no")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDelete(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, name: str, where: str) -> None:
        super().__init__()
        self._text = f"Delete {name} at {where}?"

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._text)
            with Horizontal(id="buttons"):
                yield Button("Delete", variant="error", id="yes")
                yield Button("Cancel", id="no")

    @on(Button.Pressed, "#yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def action_cancel(self) -> None:
        self.dismiss(False)


class EnvironmentStoreApp(App[None]):
    TITLE = "environment-store"
    CSS = """
    #tree { width: 36; border: round $primary; }
    #main { border: round $primary; }
    #path { padding: 0 1; text-style: bold; }
    VariableForm, NewLevelForm, ConfirmDelete, ConfirmDeleteLevel { align: center middle; }
    #dialog { width: 60; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
    #warning-title { text-style: bold; color: $error; }
    #buttons { height: auto; margin-top: 1; }
    #buttons Button { margin-right: 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "add", "Add"),
        Binding("n", "new_level", "New level"),
        Binding("x", "delete_level", "Delete level"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
        Binding("r", "toggle_resolved", "Resolved"),
        Binding("v", "toggle_values", "Values"),
        Binding("f5", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, manager: EnvironmentStoreManager) -> None:
        super().__init__()
        self.manager = manager
        self.path: Path = ()
        self.resolved = False
        self.show_values = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield HierarchyTree("root", data=(), id="tree")
            with Vertical(id="main"):
                yield Static(id="path")
                yield VariableTable(id="vars", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#vars", DataTable)
        table.add_columns("Name", "Value")
        tree = self.query_one("#tree", Tree)
        tree.show_root = True
        self._load_children(tree.root)
        tree.root.expand()
        tree.focus()
        self.refresh_table()

    # --- data -------------------------------------------------------------
    def _load_children(self, node) -> None:
        node.remove_children()
        path: Path = node.data
        try:
            names = self.manager.get_child_levels(**to_kwargs(path))
        except Exception as exc:  # noqa: BLE001 - show backend errors instead of crashing
            self.notify(f"{type(exc).__name__}: {exc}", severity="error")
            return
        for name in names:
            child = path + (name,)
            if len(child) == len(LEVELS):
                node.add_leaf(name, data=child)
            else:
                node.add(name, data=child)

    def _variables(self) -> list[Variable]:
        kwargs = to_kwargs(self.path)
        if self.resolved:
            return self.manager.get_resolved_variables(**kwargs)
        return self.manager.get_variables(**kwargs)

    def refresh_table(self) -> None:
        table = self.query_one("#vars", DataTable)
        table.clear()
        mode = "resolved" if self.resolved else "own variables"
        self.query_one("#path", Static).update(f"{describe(self.path)}  ({mode})")
        try:
            variables = sorted(self._variables(), key=lambda v: v.name)
        except Exception as exc:  # noqa: BLE001
            self.notify(f"{type(exc).__name__}: {exc}", severity="error")
            return
        for v in variables:
            table.add_row(v.name, v.value if self.show_values else "***", key=v.name)

    def _selected_name(self) -> str | None:
        table = self.query_one("#vars", DataTable)
        if table.row_count == 0:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    # --- events -----------------------------------------------------------
    @on(Tree.NodeHighlighted)
    def node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self.path = event.node.data or ()
        self.refresh_table()

    @on(Tree.NodeExpanded)
    def node_expanded(self, event: Tree.NodeExpanded) -> None:
        if not event.node.children:
            self._load_children(event.node)

    # --- actions ----------------------------------------------------------
    def action_toggle_resolved(self) -> None:
        self.resolved = not self.resolved
        self.refresh_table()

    def action_toggle_values(self) -> None:
        self.show_values = not self.show_values
        self.refresh_table()

    def action_refresh(self) -> None:
        tree = self.query_one("#tree", Tree)
        self._load_children(tree.root)
        tree.root.expand()
        self.refresh_table()

    def _save(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        try:
            self.manager.set_variable(result[0], result[1], **to_kwargs(self.path))
        except Exception as exc:  # noqa: BLE001
            self.notify(f"{type(exc).__name__}: {exc}", severity="error")
            return
        self.notify(f"Saved {result[0]}")
        self.refresh_table()

    def action_add(self) -> None:
        self.push_screen(VariableForm(), self._save)

    def action_new_level(self) -> None:
        kind = child_kind(self.path)
        if kind is None:
            self.notify("A service has no child levels", severity="warning")
            return
        parent = describe(self.path)
        parent_path = self.path

        def done(result: tuple[str, str, str] | None) -> None:
            if result is None:
                return
            level, name, value = result
            new_path = parent_path + (level,)
            try:
                self.manager.set_variable(name, value, **to_kwargs(new_path))
            except Exception as exc:  # noqa: BLE001
                self.notify(f"{type(exc).__name__}: {exc}", severity="error")
                return
            self.notify(f"Created {kind} {level}")
            self._reveal(new_path)

        self.push_screen(NewLevelForm(kind, parent), done)

    def action_delete_level(self) -> None:
        path = self.path
        if not path:
            self.notify("The root level cannot be deleted", severity="warning")
            return
        kind, name = level_kind(path), path[-1]
        try:
            variables, sub_levels = self.manager.count_level(**to_kwargs(path))
        except Exception as exc:  # noqa: BLE001
            self.notify(f"{type(exc).__name__}: {exc}", severity="error")
            return

        def done(typed_name: str | None) -> None:
            if typed_name is None:
                return
            try:
                deleted = self.manager.delete_level(**to_kwargs(path), confirm=typed_name)
            except Exception as exc:  # noqa: BLE001
                self.notify(f"{type(exc).__name__}: {exc}", severity="error")
                return
            self.notify(f"Deleted {kind} {name} ({deleted} variable(s))")
            self._reveal(path[:-1])

        self.push_screen(
            ConfirmDeleteLevel(kind, name, describe(path), variables, sub_levels), done
        )

    def _reveal(self, path: Path) -> None:
        """Reload the tree along ``path`` and move the cursor to its last node."""
        tree = self.query_one("#tree", Tree)
        node = tree.root
        for depth in range(len(path)):
            self._load_children(node)
            node.expand()
            match = next((c for c in node.children if c.data == path[: depth + 1]), None)
            if match is None:
                return
            node = match
        if node.allow_expand:
            self._load_children(node)
            node.expand()
        # The tree rebuilds its lines lazily, so move the cursor once it has refreshed.
        self.call_after_refresh(tree.move_cursor, node)
        tree.focus()

    def action_edit(self) -> None:
        name = self._selected_name()
        if name is None or self.resolved:
            if self.resolved:
                self.notify("Switch off the resolved view to edit", severity="warning")
            return
        current = self.manager.get_variable(name, **to_kwargs(self.path)) or ""
        self.push_screen(VariableForm(name, current), self._save)

    def action_delete(self) -> None:
        name = self._selected_name()
        if name is None or self.resolved:
            if self.resolved:
                self.notify("Switch off the resolved view to delete", severity="warning")
            return

        def done(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self.manager.delete_variable(name, **to_kwargs(self.path))
            except Exception as exc:  # noqa: BLE001
                self.notify(f"{type(exc).__name__}: {exc}", severity="error")
                return
            self.notify(f"Deleted {name}")
            self.refresh_table()

        self.push_screen(ConfirmDelete(name, describe(self.path)), done)


def run(manager: EnvironmentStoreManager) -> None:
    EnvironmentStoreApp(manager).run()
