"""`envs rm-store`: delete a store, no key needed, confirmed (spec §6.4, D21, D33, D35)."""

import pytest

from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _names(cli: CliHarness) -> list[str]:
    return [info.name for info in cli.store().list_stores()]


@pytest.mark.parametrize("flag", ["-y", "--yes"])
def test_rm_store_with_yes_deletes_the_store(cli: CliHarness, flag: str) -> None:
    cli.store().create_store("a")
    cli.store().create_store("b")

    result = cli.invoke("rm-store", "a", flag)

    assert_exit(result, 0)
    assert _names(cli) == ["b"]
    assert result.stdout == ""
    assert result.stderr == "deleted store 'a'\n"


def test_rm_store_deletes_an_encrypted_store_without_its_key(cli: CliHarness) -> None:
    cli.store().create_store("a", encrypt=True, key=Passphrase(text="lost"))

    result = cli.invoke("rm-store", "a", "-y", stdin_tty=True)

    assert_exit(result, 0)
    assert _names(cli) == []


def test_rm_store_of_a_missing_store_fails_with_two_without_asking(cli_json: CliHarness) -> None:
    prompter = RecordingPrompter()

    result = cli_json.invoke("rm-store", "missing", stdin_tty=True, prompter=prompter)

    assert_exit(result, 2)
    assert prompter.prompts == []
    assert "missing" in result.stderr


def test_rm_store_without_a_terminal_and_without_yes_fails_with_one(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("rm-store", "a")

    assert_exit(result, 1)
    assert "-y" in result.stderr
    assert _names(cli_json) == ["a"]


def test_rm_store_with_noinput_on_a_terminal_fails_with_one(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("--noinput", "rm-store", "a", stdin_tty=True)

    assert_exit(result, 1)
    assert _names(cli_json) == ["a"]


def test_rm_store_asks_on_a_terminal_and_deletes_on_yes(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    prompter = RecordingPrompter("y")

    result = cli_json.invoke("rm-store", "a", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert prompter.prompts == [("confirm", "Delete store 'a'?")]
    assert _names(cli_json) == []


def test_rm_store_answered_no_fails_with_one_and_keeps_the_store(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("rm-store", "a", stdin_tty=True, prompter=RecordingPrompter("n"))

    assert_exit(result, 1)
    assert _names(cli_json) == ["a"]


def test_rm_store_with_an_invalid_name_fails_with_one(cli_json: CliHarness) -> None:
    result = cli_json.invoke("rm-store", "Bad", "-y")

    assert_exit(result, 1)
