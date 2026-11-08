"""Path completion of the TUI's path inputs (D57): the suggester and the Tab key."""

import asyncio
import os
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from environment_store.core.errors import ValidationError
from environment_store.tui import paths
from environment_store.tui.paths import PathInput, PathSuggester, complete_path, expand_path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """`tmp_path` (also the working directory) with a few files and directories."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "prod.env").write_text("")
    (tmp_path / "configs" / "Prod.json").write_text("")
    (tmp_path / "cache.txt").write_text("")
    (tmp_path / "docs").mkdir()
    (tmp_path / ".env").write_text("")
    (tmp_path / ".hidden_dir").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("ca", "cache.txt"),
        ("co", "configs/"),
        ("c", "cache.txt"),
        ("d", "docs/"),
        ("docs", "docs/"),
        ("configs/p", "configs/prod.env"),
        ("configs/P", "configs/Prod.json"),
        ("./co", "./configs/"),
        ("configs/", "configs/Prod.json"),
        (".e", ".env"),
        (".h", ".hidden_dir/"),
    ],
)
def test_complete_path_suggests_the_first_matching_entry(
    tree: Path, typed: str, expected: str
) -> None:
    assert complete_path(typed) == expected


def test_complete_path_works_with_absolute_paths(tree: Path) -> None:
    assert complete_path(f"{tree}/do") == f"{tree}/docs/"


def test_complete_path_is_case_sensitive(tree: Path) -> None:
    assert complete_path("Co") is None


@pytest.mark.parametrize(
    "typed", ["cache.txt", "x", "nothing/he", "cache.txt/a", "configs/prod.env"]
)
def test_complete_path_without_a_longer_match_suggests_nothing(tree: Path, typed: str) -> None:
    assert complete_path(typed) is None


def test_complete_path_skips_hidden_entries_unless_a_dot_is_typed(tree: Path) -> None:
    (tree / "docs" / ".secret").write_text("")
    assert complete_path("docs/") is None
    assert complete_path("docs/.") == "docs/.secret"


def test_complete_path_expands_the_home_directory_and_keeps_the_tilde(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tree))
    assert complete_path("~/con") == "~/configs/"
    assert complete_path("~") == "~/"


@pytest.mark.parametrize("typed", ["~nosuchuser_zz/a", "~nosuchuser_zz", "a\0b/c"])
def test_complete_path_ignores_unknown_users_and_invalid_paths(tree: Path, typed: str) -> None:
    assert complete_path(typed) is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every directory")
def test_complete_path_ignores_an_unreadable_directory(tree: Path) -> None:
    locked = tree / "locked"
    locked.mkdir()
    (locked / "inner").write_text("")
    locked.chmod(0o000)
    try:
        assert complete_path("locked/i") is None
    finally:
        locked.chmod(0o700)


class _Entry:
    """A directory entry that counts how often it is asked whether it is a directory."""

    def __init__(self, name: str, *, directory: bool, asked: list[str]) -> None:
        self.name = name
        self._directory = directory
        self._asked = asked

    def is_dir(self) -> bool:
        self._asked.append(self.name)
        return self._directory


@pytest.mark.parametrize(
    ("typed", "expected", "checked"),
    [
        ("d", "d2", ["d2"]),
        ("dat", "data/", ["data"]),
        ("data", "data/", ["data"]),
        ("e", "e1", ["e", "e1"]),
    ],
)
def test_complete_path_asks_only_the_chosen_entries_whether_they_are_directories(
    monkeypatch: pytest.MonkeyPatch, typed: str, expected: str, checked: list[str]
) -> None:
    asked: list[str] = []
    names = {"d9": False, "data": True, "d2": False, "e": False, "e1": False, "other": False}
    entries = [_Entry(name, directory=directory, asked=asked) for name, directory in names.items()]

    @contextmanager
    def scandir(_directory: Path) -> Generator[list[_Entry]]:
        yield entries

    monkeypatch.setattr(paths.os, "scandir", scandir)

    assert complete_path(typed) == expected
    assert asked == checked


def test_path_suggester_looks_up_paths_outside_the_event_loop_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[threading.Thread] = []

    def lookup(typed: str) -> str:
        threads.append(threading.current_thread())
        return f"{typed}/"

    monkeypatch.setattr(paths, "complete_path", lookup)

    assert asyncio.run(PathSuggester().get_suggestion("do")) == "do/"
    assert threads
    assert threads[0] is not threading.current_thread()


def test_path_suggester_is_case_sensitive_and_uncached(tree: Path) -> None:
    suggester = PathSuggester()
    assert suggester.case_sensitive
    assert suggester.cache is None
    assert asyncio.run(suggester.get_suggestion("do")) == "docs/"
    (tree / "dotfile").write_text("")
    assert asyncio.run(suggester.get_suggestion("dot")) == "dotfile"


def test_expand_path_expands_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert expand_path("~/a.key", what="key file") == tmp_path / "a.key"
    assert expand_path(" ./b.env ", what="output file") == Path("b.env")


def test_expand_path_names_an_unknown_home_directory(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match=r"key file path '~nosuchuser_zz/a' names an unknown"):
        expand_path("~nosuchuser_zz/a", what="key file")


class _PathApp(App[None]):
    """Two path inputs and a plain one, for the Tab key."""

    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def compose(self) -> ComposeResult:
        yield PathInput(id="first")
        yield Input(id="second")


def _run(scenario_keys: list[str]) -> tuple[str, str | None]:
    app = _PathApp()
    result: list[tuple[str, str | None]] = []

    async def main() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for key in scenario_keys:
                await pilot.press(key)
                await pilot.pause()
                await pilot.pause()
            focused = app.focused
            result.append(
                (app.query_one("#first", Input).value, None if focused is None else focused.id)
            )

    asyncio.run(main())
    return result[0]


@pytest.mark.usefixtures("tree")
def test_tab_accepts_the_shown_suggestion() -> None:
    assert _run(["d", "o", "tab"]) == ("docs/", "first")


@pytest.mark.usefixtures("tree")
def test_right_accepts_the_shown_suggestion() -> None:
    assert _run(["d", "o", "right"]) == ("docs/", "first")


@pytest.mark.usefixtures("tree")
def test_tab_without_a_suggestion_moves_the_focus() -> None:
    assert _run(["x", "tab"]) == ("x", "second")


@pytest.mark.usefixtures("tree")
def test_tab_with_the_cursor_inside_the_text_moves_the_focus() -> None:
    assert _run(["d", "o", "left", "tab"]) == ("do", "second")


def test_path_input_shows_tab_in_the_footer_bindings() -> None:
    [binding] = [b for b in PathInput.BINDINGS if not isinstance(b, tuple) and b.key == "tab"]
    assert binding.show
    assert binding.description == "Complete path"
