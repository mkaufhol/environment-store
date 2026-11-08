"""`TerminalPrompter`: prompts on stderr, never on stdout."""

import getpass
import io
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
import typer

from environment_store.cli import prompts
from environment_store.cli.prompts import TerminalPrompter
from environment_store.core.errors import ValidationError

if TYPE_CHECKING:
    from environment_store.config.prompt import Prompter


@dataclass
class FakeTerminal:
    """Scripted answers for `read_hidden` / `read_line`; records everything written."""

    answers: list[str | BaseException]
    asked: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)

    def _next(self) -> str:
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def read_hidden(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self._next()

    def read_line(self) -> str:
        return self._next()

    def write(self, text: str) -> None:
        self.written.append(text)

    def prompter(self) -> TerminalPrompter:
        return TerminalPrompter(
            read_hidden=self.read_hidden, read_line=self.read_line, write=self.write
        )


def test_terminal_prompter_has_no_answers_until_asked() -> None:
    # The annotation makes ty check that TerminalPrompter satisfies the Prompter protocol.
    prompter: Prompter = FakeTerminal([]).prompter()

    assert isinstance(prompter, TerminalPrompter)


def test_secret_asks_once_with_the_prompt_as_given() -> None:
    terminal = FakeTerminal(["s3cret"])

    answer = terminal.prompter().secret("Key or passphrase for store 'a': ")

    assert answer == "s3cret"
    assert terminal.asked == ["Key or passphrase for store 'a': "]
    assert terminal.written == []


def test_new_secret_returns_the_answer_when_both_entries_match() -> None:
    terminal = FakeTerminal(["pw", "pw"])

    assert terminal.prompter().new_secret("New passphrase: ") == "pw"
    assert terminal.asked == ["New passphrase: ", "Repeat to confirm: "]


def test_new_secret_asks_again_after_one_mismatch() -> None:
    terminal = FakeTerminal(["pw", "typo", "pw2", "pw2"])

    assert terminal.prompter().new_secret("New passphrase: ") == "pw2"
    assert terminal.written == ["values do not match\n"]
    assert len(terminal.asked) == 4


def test_new_secret_gives_up_after_three_mismatches_without_showing_the_values() -> None:
    terminal = FakeTerminal(["a1", "b1", "a2", "b2", "a3", "b3"])

    with pytest.raises(ValidationError, match="did not match") as raised:
        terminal.prompter().new_secret("New passphrase: ")

    assert not any(value in str(raised.value) for value in ["a1", "b1", "a3", "b3"])
    assert terminal.answers == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("y\n", True),
        ("Y\n", True),
        ("yes\n", True),
        ("YES\n", True),
        ("  yes  \n", True),
        ("n\n", False),
        ("no\n", False),
        ("\n", False),
        ("yep\n", False),
    ],
)
def test_confirm_only_accepts_y_or_yes(line: str, *, expected: bool) -> None:
    terminal = FakeTerminal([line])

    assert terminal.prompter().confirm("Delete store 'a'?") is expected
    assert terminal.written == ["Delete store 'a'? [y/N]: "]


def test_confirm_at_end_of_input_aborts() -> None:
    terminal = FakeTerminal([""])

    with pytest.raises(typer.Abort):
        terminal.prompter().confirm("Delete store 'a'?")


@pytest.mark.parametrize(
    "ask",
    [
        lambda prompter: prompter.secret("Key: "),
        lambda prompter: prompter.new_secret("New: "),
    ],
    ids=["secret", "new_secret"],
)
def test_end_of_input_at_a_hidden_prompt_aborts(ask: Callable[[TerminalPrompter], str]) -> None:
    terminal = FakeTerminal([EOFError()])

    with pytest.raises(typer.Abort):
        ask(terminal.prompter())


@pytest.mark.parametrize(
    "ask",
    [
        lambda prompter: prompter.secret("Key: "),
        lambda prompter: prompter.new_secret("New: "),
        lambda prompter: prompter.confirm("Sure?"),
    ],
    ids=["secret", "new_secret", "confirm"],
)
def test_ctrl_c_at_a_prompt_is_not_caught(ask: Callable[[TerminalPrompter], object]) -> None:
    # typer turns an escaping KeyboardInterrupt into exit code 130.
    terminal = FakeTerminal([KeyboardInterrupt()])

    with pytest.raises(KeyboardInterrupt):
        ask(terminal.prompter())


# --- the default callables ---------------------------------------------------------------------


class RecordingStream(io.StringIO):
    flushed: bool = False

    def flush(self) -> None:
        self.flushed = True
        super().flush()


@pytest.fixture
def stderr() -> RecordingStream:
    return RecordingStream()


def test_default_read_hidden_uses_getpass_on_stderr(
    monkeypatch: pytest.MonkeyPatch, stderr: RecordingStream
) -> None:
    calls: list[tuple[str, object]] = []

    def fake_getpass(prompt: str = "Password: ", stream: object = None) -> str:
        calls.append((prompt, stream))
        return "typed"

    monkeypatch.setattr(getpass, "getpass", fake_getpass)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert prompts.read_hidden("Key: ") == "typed"
    assert calls == [("Key: ", stderr)]


def test_default_read_line_reads_one_line_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("yes\nrest\n"))

    assert prompts.read_line() == "yes\n"


def test_default_write_writes_to_stderr_and_flushes(
    monkeypatch: pytest.MonkeyPatch, stderr: RecordingStream
) -> None:
    monkeypatch.setattr(sys, "stderr", stderr)

    prompts.write("Sure? [y/N]: ")

    assert stderr.getvalue() == "Sure? [y/N]: "
    assert stderr.flushed


def test_default_prompter_uses_the_module_functions() -> None:
    prompter = TerminalPrompter()

    assert prompter.read_hidden is prompts.read_hidden
    assert prompter.read_line is prompts.read_line
    assert prompter.write is prompts.write
