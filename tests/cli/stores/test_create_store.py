"""`envs create-store`: plaintext and encrypted stores, key options (§6.3, D3, PD 24, PD 33)."""

import stat
from pathlib import Path

import pytest

from environment_store.core.models import KeyMode
from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_text
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _names(cli: CliHarness) -> list[str]:
    return [info.name for info in cli.store().list_stores()]


def _assert_readable_with(cli: CliHarness, name: str, key: Path | Passphrase) -> None:
    store = cli.store()
    store.set(name, "PROBE", "1", key=key)
    assert store.variables(name, key=key) == {"PROBE": "1"}


def test_create_store_creates_a_plaintext_store(cli: CliHarness) -> None:
    result = cli.invoke("create-store", "base_conf")

    assert_exit(result, 0)
    info = cli.store().store_info("base_conf")
    assert not info.encrypted
    assert result.stdout == ""
    assert result.stderr == "created store 'base_conf'\n"


def test_create_store_with_an_existing_key_file(cli: CliHarness) -> None:
    key = cli.key_file()

    result = cli.invoke("create-store", "secret", "-e", "-k", str(key))

    assert_exit(result, 0)
    assert cli.store().store_info("secret").key_mode is KeyMode.KEYFILE
    _assert_readable_with(cli, "secret", key)


def test_create_store_reads_the_key_file_from_stdin(cli_json: CliHarness) -> None:
    text = generate_key_text()
    key = cli_json.passphrase_file(text, name="copy.key")

    result = cli_json.invoke("create-store", "secret", "--encrypt", "--key", "-", input=text)

    assert_exit(result, 0)
    _assert_readable_with(cli_json, "secret", key)


def test_create_store_generates_a_private_key_file(cli: CliHarness) -> None:
    key = cli.root / "new.key"

    result = cli.invoke("create-store", "secret", "-e", "--generate-key", str(key))

    assert_exit(result, 0)
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert cli.store().store_info("secret").key_mode is KeyMode.KEYFILE
    _assert_readable_with(cli, "secret", key)


def test_create_store_with_a_piped_passphrase(cli: CliHarness) -> None:
    result = cli.invoke("create-store", "secret", "-e", "--passphrase", input="pw\n")

    assert_exit(result, 0)
    assert cli.store().store_info("secret").key_mode is KeyMode.PASSPHRASE
    _assert_readable_with(cli, "secret", Passphrase(text="pw"))


def test_create_store_asks_for_a_new_passphrase_on_a_terminal(cli_json: CliHarness) -> None:
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke(
        "create-store", "secret", "-e", "--passphrase", stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert [kind for kind, _text in prompter.prompts] == ["new_secret"]
    _assert_readable_with(cli_json, "secret", Passphrase(text="pw"))


def test_create_store_with_noinput_on_a_terminal_fails_with_four_without_reading_stdin(
    cli_json: CliHarness,
) -> None:
    result = cli_json.invoke(
        "--noinput", "create-store", "secret", "-e", "--passphrase", input="pw\n", stdin_tty=True
    )

    assert_exit(result, 4)
    assert _names(cli_json) == []


def test_create_store_refuses_generate_key_to_stdout(cli_json: CliHarness) -> None:
    result = cli_json.invoke("create-store", "secret", "-e", "--generate-key", "-")

    assert_exit(result, 1)
    assert "envs keygen -" in result.stderr
    assert not (cli_json.root / "-").exists()
    assert _names(cli_json) == []


def test_create_store_of_an_existing_store_fails_with_three(cli: CliHarness) -> None:
    cli.store().create_store("a")

    result = cli.invoke("create-store", "a")

    assert_exit(result, 3)
    assert "already exists" in result.stderr


def test_create_store_of_an_existing_store_removes_the_generated_key_file(
    cli_json: CliHarness,
) -> None:
    cli_json.store().create_store("a")
    key = cli_json.root / "new.key"

    result = cli_json.invoke("create-store", "a", "-e", "--generate-key", str(key))

    assert_exit(result, 3)
    assert not key.exists()
    assert not cli_json.store().store_info("a").encrypted


@pytest.mark.parametrize("name", ["Upper", "-dash", "a b", "x" * 64])
def test_create_store_with_an_invalid_name_fails_with_one_and_creates_nothing(
    cli_json: CliHarness, name: str
) -> None:
    key = cli_json.root / "new.key"

    result = cli_json.invoke("create-store", "-e", "--generate-key", str(key), "--", name)

    assert_exit(result, 1)
    assert _names(cli_json) == []
    assert not key.exists()


@pytest.mark.parametrize(
    "options",
    [["-k", "a.key"], ["--generate-key", "new.key"], ["--passphrase"]],
    ids=["key", "generate-key", "passphrase"],
)
def test_create_store_key_options_need_encrypt(cli_json: CliHarness, options: list[str]) -> None:
    cli_json.key_file()

    result = cli_json.invoke("create-store", "secret", *options, input="pw\n")

    assert_exit(result, 1)
    assert "-e" in result.stderr
    assert _names(cli_json) == []
    assert not (cli_json.root / "new.key").exists()


def test_create_store_encrypt_needs_a_key_option(cli_json: CliHarness) -> None:
    result = cli_json.invoke("create-store", "secret", "-e")

    assert_exit(result, 1)
    assert "--generate-key" in result.stderr
    assert _names(cli_json) == []


def test_create_store_encrypt_takes_only_one_key_option(cli_json: CliHarness) -> None:
    key = cli_json.key_file()

    result = cli_json.invoke(
        "create-store", "secret", "-e", "-k", str(key), "--passphrase", input="pw\n"
    )

    assert_exit(result, 1)
    assert "only one" in result.stderr
    assert _names(cli_json) == []


def test_create_store_with_a_passphrase_file_as_key_file_fails_with_four(
    cli_json: CliHarness,
) -> None:
    passphrase = cli_json.passphrase_file("not a key\n")

    result = cli_json.invoke("create-store", "secret", "-e", "-k", str(passphrase))

    assert_exit(result, 4)
    assert _names(cli_json) == []


def test_create_store_with_a_missing_key_file_fails_with_four(cli_json: CliHarness) -> None:
    result = cli_json.invoke("create-store", "secret", "-e", "-k", "missing.key")

    assert_exit(result, 4)
    assert "missing.key" in result.stderr
    assert _names(cli_json) == []
