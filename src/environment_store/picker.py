"""Interactive level picker: choose a hierarchy level from a tree in the terminal."""

import os
import shutil
import sys
from collections.abc import Callable, Iterator
from typing import TextIO

from environment_store.core.hierarchy import LEVELS, Path, level_kind

Loader = Callable[[Path], list[str]]

HELP = "↑/↓ move  →/← expand/collapse  enter select  q cancel"

_ESCAPES = {
    b"[A": "up",
    b"OA": "up",
    b"[B": "down",
    b"OB": "down",
    b"[C": "right",
    b"OC": "right",
    b"[D": "left",
    b"OD": "left",
    b"[H": "home",
    b"OH": "home",
    b"[F": "end",
    b"OF": "end",
}


class PickerCancelled(Exception):
    """The user left the picker without choosing a level."""


class _Node:
    __slots__ = ("children", "expanded", "path")

    def __init__(self, path: Path) -> None:
        self.path = path
        self.children: list[_Node] | None = None  # None until loaded
        self.expanded = False

    @property
    def is_leaf(self) -> bool:
        return len(self.path) == len(LEVELS) or self.children == []


class LevelTree:
    """
    The state of the picker: a lazily loaded tree of levels and a cursor. Does no terminal I/O.

    ``load`` returns the names of the levels below a path. Without ``allow_root`` the root level
    is hidden and the organisations are the top of the tree.
    """

    def __init__(self, load: Loader, allow_root: bool = True) -> None:
        self._load = load
        self.allow_root = allow_root
        self.root = _Node(())
        self._expand(self.root)
        self.cursor = 0
        self.top = 0

    def _expand(self, node: _Node) -> None:
        if node.children is None:
            node.children = [_Node(node.path + (name,)) for name in self._load(node.path)]
        node.expanded = bool(node.children)

    def visible(self) -> list[_Node]:
        nodes: list[_Node] = []

        def walk(node: _Node) -> None:
            nodes.append(node)
            if node.expanded and node.children:
                for child in node.children:
                    walk(child)

        walk(self.root)
        return nodes if self.allow_root else nodes[1:]

    def press(self, key: str) -> Path | None:
        """Handle one key. Returns the chosen path on ``enter``, otherwise ``None``."""
        nodes = self.visible()
        node = nodes[self.cursor]
        if key in ("up", "k"):
            self.cursor = max(0, self.cursor - 1)
        elif key in ("down", "j"):
            self.cursor = min(len(nodes) - 1, self.cursor + 1)
        elif key == "home":
            self.cursor = 0
        elif key == "end":
            self.cursor = len(nodes) - 1
        elif key in ("right", "l"):
            if node.expanded:
                self.cursor += 1
            elif not node.is_leaf:
                self._expand(node)
        elif key in ("left", "h"):
            if node.expanded:
                node.expanded = False
            else:
                parents = [i for i, n in enumerate(nodes) if n.path == node.path[:-1]]
                if node.path and parents:
                    self.cursor = parents[0]
        elif key == " ":
            if node.expanded:
                node.expanded = False
            elif not node.is_leaf:
                self._expand(node)
        elif key in ("enter", "\r", "\n"):
            return node.path
        elif key in ("q", "esc", "ctrl-c"):
            raise PickerCancelled
        return None

    def render(self, height: int, width: int) -> list[str]:
        """The tree rows that fit into ``height`` lines, scrolled to keep the cursor visible."""
        nodes = self.visible()
        self.top = min(max(self.top, self.cursor - height + 1), self.cursor)
        offset = 0 if self.allow_root else 1
        lines = []
        for i, node in enumerate(nodes[self.top : self.top + height], start=self.top):
            if node.is_leaf:
                marker = " "
            else:
                marker = "▾" if node.expanded else "▸"
            name = node.path[-1] if node.path else "root"
            kind = level_kind(node.path) if node.path else "variables shared by every level"
            indent = "  " * (len(node.path) - offset)
            text = f"{'›' if i == self.cursor else ' '} {indent}{marker} {name}"
            label = f"  ({kind})"
            text, label = text[: width - 1], label[: max(0, width - 1 - len(text))]
            if i == self.cursor:
                lines.append(f"\x1b[7m{text}\x1b[27m\x1b[2m{label}\x1b[22m")
            else:
                lines.append(f"{text}\x1b[2m{label}\x1b[22m")
        return lines


def pick_level(
    load: Loader,
    title: str,
    allow_root: bool = True,
    *,
    keys: Iterator[str] | None = None,
    out: TextIO | None = None,
) -> Path:
    """
    Let the user choose a level from a tree drawn on ``out`` (stderr by default).

    Keys are read from the terminal unless ``keys`` is given. Raises ``PickerCancelled`` when the
    user quits.
    """
    tree = LevelTree(load, allow_root)
    if not tree.visible():
        raise PickerCancelled("The store has no levels yet.")
    out = out or sys.stderr
    keys = keys if keys is not None else _terminal_keys()
    drawn = 0
    out.write("\x1b[?25l")
    try:
        while True:
            size = shutil.get_terminal_size()
            lines = [
                f"\x1b[1m{title[: size.columns - 1]}\x1b[22m",
                *tree.render(max(3, size.lines - 3), size.columns),
                f"\x1b[2m{HELP[: size.columns - 1]}\x1b[22m",
            ]
            out.write((f"\x1b[{drawn}F" if drawn else "") + "\x1b[J" + "\n".join(lines) + "\n")
            out.flush()
            drawn = len(lines)
            choice = tree.press(next(keys))
            if choice is not None:
                return choice
    except (KeyboardInterrupt, StopIteration) as exc:
        raise PickerCancelled from exc
    finally:
        out.write((f"\x1b[{drawn}F\x1b[J" if drawn else "") + "\x1b[?25h")
        out.flush()
        close = getattr(keys, "close", None)
        if close:
            close()


def _terminal_keys() -> Iterator[str]:
    """Read single key presses from the terminal on stdin, as names like ``"up"`` or ``"q"``."""
    if sys.platform == "win32":
        import msvcrt

        special = {"H": "up", "P": "down", "K": "left", "M": "right", "G": "home", "O": "end"}
        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                yield special.get(msvcrt.getwch(), "")
            else:
                yield {"\r": "enter", "\x03": "ctrl-c", "\x1b": "esc"}.get(ch, ch)
    else:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                ch = os.read(fd, 1)
                if ch == b"\x1b":
                    seq = b""
                    while select.select([fd], [], [], 0.05)[0]:
                        seq += os.read(fd, 1)
                        if seq[-1:].isalpha() or seq.endswith(b"~"):
                            break
                    yield _ESCAPES.get(seq, "" if seq else "esc")
                elif ch in (b"\r", b"\n"):
                    yield "enter"
                else:
                    yield ch.decode(errors="ignore")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
