import getpass
import io

import pytest

from environment_store.config.prompt import GetpassPrompter, Prompter
from environment_store.core.errors import ValidationError


class _Answers:
    """A fake `getpass.getpass` that returns queued answers and records the prompts."""

    answers: list[str]
    prompts: list[str]

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt: str = "Password: ", stream: object = None) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


def _prompter(
    monkeypatch: pytest.MonkeyPatch, *answers: str, stdin: str = ""
) -> tuple[GetpassPrompter, _Answers, io.StringIO]:
    fake = _Answers(*answers)
    monkeypatch.setattr(getpass, "getpass", fake)
    errors = io.StringIO()
    return GetpassPrompter(input_stream=io.StringIO(stdin), error_stream=errors), fake, errors


def test_getpass_prompter_is_a_prompter() -> None:
    prompter: Prompter = GetpassPrompter()

    assert isinstance(prompter, GetpassPrompter)


def test_secret_asks_getpass_once(monkeypatch: pytest.MonkeyPatch) -> None:
    prompter, fake, _ = _prompter(monkeypatch, "open sesame")

    assert prompter.secret("Key for 'a': ") == "open sesame"
    assert fake.prompts == ["Key for 'a': "]


def test_new_secret_asks_twice_and_returns_the_matching_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompter, fake, _ = _prompter(monkeypatch, "open sesame", "open sesame")

    assert prompter.new_secret("New passphrase: ") == "open sesame"
    assert fake.prompts == ["New passphrase: ", "Repeat to confirm: "]


def test_new_secret_refuses_answers_that_differ_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompter, _, _ = _prompter(monkeypatch, "first-answer", "second-answer")

    with pytest.raises(ValidationError, match="do not match") as caught:
        prompter.new_secret("New passphrase: ")

    assert "first-answer" not in str(caught.value)
    assert "second-answer" not in str(caught.value)


@pytest.mark.parametrize(("line", "expected"), [("y\n", True), ("YES\n", True), (" yes ", True)])
def test_confirm_accepts_yes(
    monkeypatch: pytest.MonkeyPatch,
    line: str,
    expected: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    prompter, _, errors = _prompter(monkeypatch, stdin=line)

    assert prompter.confirm("Delete store 'a'?") is expected
    assert errors.getvalue() == "Delete store 'a'? [y/N] "


@pytest.mark.parametrize("line", ["\n", "n\n", "no\n", "", "yess\n"])
def test_confirm_refuses_anything_else(monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    prompter, _, _ = _prompter(monkeypatch, stdin=line)

    assert prompter.confirm("Delete store 'a'?") is False


def test_confirm_defaults_to_the_process_streams(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))

    assert GetpassPrompter().confirm("Go?") is True
    assert capsys.readouterr().err == "Go? [y/N] "
