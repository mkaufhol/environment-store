"""A new store key or passphrase read from stdin is never saved by envs: warn about it."""

from collections.abc import Callable
from typing import Final

import pytest

from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _warning(store: str, what: str = "key") -> str:
    return (
        f"Warning: envs does not save this {what}; keep it, or store '{store}' cannot be read again"
    )


def _plain(cli: CliHarness) -> None:
    cli.store().create_store("src")


def _encrypted(cli: CliHarness) -> None:
    cli.store().create_store("src", encrypt=True, key=Passphrase(text="old"))


# (arrange, arguments before the new-secret option, the store the warning names)
_COMMANDS: dict[str, tuple[Callable[[CliHarness], None], list[str], str]] = {
    "create-store": (lambda _: None, ["create-store", "dst", "-e"], "dst"),
    "encrypt": (_plain, ["encrypt", "-s", "src"], "src"),
    "rekey": (_encrypted, ["rekey", "-s", "src", "-k", "OLD"], "src"),
    "cp-store": (_plain, ["cp-store", "src", "dst"], "dst"),
    "mv-store": (_plain, ["mv-store", "src", "dst"], "dst"),
}


def _args(cli: CliHarness, command: str) -> tuple[list[str], str, str]:
    arrange, args, store = _COMMANDS[command]
    arrange(cli)
    old = str(cli.passphrase_file("old\n", name="old.txt"))
    return (
        [old if arg == "OLD" else arg for arg in args],
        store,
        "-k" if command == "create-store" else "--new-key",
    )


@pytest.mark.parametrize("command", list(_COMMANDS))
def test_new_key_from_stdin_warns_that_it_is_not_saved(cli_json: CliHarness, command: str) -> None:
    args, store, option = _args(cli_json, command)
    key = cli_json.key_file("new.key").read_bytes()

    result = cli_json.invoke(*args, option, "-", input=key)

    assert_exit(result, 0)
    assert _warning(store) in result.stderr


@pytest.mark.parametrize("command", list(_COMMANDS))
def test_new_passphrase_from_stdin_warns_that_it_is_not_saved(
    cli_json: CliHarness, command: str
) -> None:
    args, store, _ = _args(cli_json, command)

    result = cli_json.invoke(*args, "--passphrase", input="new pw\n")

    assert_exit(result, 0)
    assert _warning(store, "passphrase") in result.stderr


@pytest.mark.parametrize("command", list(_COMMANDS))
def test_new_key_file_gives_no_warning(cli_json: CliHarness, command: str) -> None:
    args, _, option = _args(cli_json, command)

    result = cli_json.invoke(*args, option, str(cli_json.key_file("new.key")))

    assert_exit(result, 0)
    assert "does not save" not in result.stderr


def test_generated_key_file_gives_no_warning(cli_json: CliHarness) -> None:
    result = cli_json.invoke("create-store", "dst", "-e", "--generate-key", "new.key")

    assert_exit(result, 0)
    assert "does not save" not in result.stderr


def test_prompted_new_passphrase_gives_no_warning(cli_json: CliHarness) -> None:
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke(
        "create-store", "dst", "-e", "--passphrase", stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert "does not save" not in result.stderr


def test_key_of_an_existing_store_from_stdin_gives_no_warning(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("src", encrypt=True, key=key)

    result = cli_json.invoke("cp-store", "src", "dst", "-k", "-", input=key.read_bytes())

    assert_exit(result, 0)
    assert "does not save" not in result.stderr


# The commands that create the store the new secret encrypts.
_CREATING: Final = ("create-store", "cp-store", "mv-store")


@pytest.mark.parametrize("command", _CREATING)
def test_no_warning_when_the_target_store_already_exists(
    cli_json: CliHarness, command: str
) -> None:
    args, store, option = _args(cli_json, command)
    cli_json.store().create_store(store)
    key = cli_json.key_file("new.key").read_bytes()

    result = cli_json.invoke(*args, option, "-", input=key)

    assert_exit(result, 3)
    assert "does not save" not in result.stderr
    assert not cli_json.store().store_info(store).encrypted


def test_no_warning_when_rekey_fails(cli_json: CliHarness) -> None:
    args, _, option = _args(cli_json, "rekey")
    wrong = str(cli_json.passphrase_file("wrong\n", name="wrong.txt"))
    args = [wrong if arg.endswith("old.txt") else arg for arg in args]

    result = cli_json.invoke(*args, option, "-", input=cli_json.key_file("new.key").read_bytes())

    assert result.exit_code != 0
    assert "does not save" not in result.stderr
