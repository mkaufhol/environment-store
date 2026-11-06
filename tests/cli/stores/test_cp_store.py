"""`envs cp-store`: copies, re-encryption and target encryption (spec §6.5, D4, D5, D15, D33)."""

import stat
from pathlib import Path

import pytest

from environment_store.core.connection import open_adapter
from environment_store.core.errors import DecryptionError
from environment_store.core.models import KeyMode
from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, connection_for

_VARIABLES = {"HOST": "localhost", "TOKEN": "s3cret"}


def _names(cli: CliHarness) -> list[str]:
    return [info.name for info in cli.store().list_stores()]


def _plain_source(cli: CliHarness) -> None:
    store = cli.store()
    store.create_store("src")
    store.set_many("src", _VARIABLES)


def _encrypted_source(cli: CliHarness) -> Path:
    key = cli.key_file("src.key")
    store = cli.store()
    store.create_store("src", encrypt=True, key=key)
    store.set_many("src", _VARIABLES, key=key)
    return key


def _ciphertext(connection: str, name: str) -> bytes | None:
    with open_adapter(connection) as adapter:
        return adapter.read_store(name).ciphertext


def test_cp_store_copies_a_plaintext_store(cli: CliHarness) -> None:
    _plain_source(cli)

    result = cli.invoke("cp-store", "src", "dst")

    assert_exit(result, 0)
    assert cli.store().variables("dst") == _VARIABLES
    assert cli.store().variables("src") == _VARIABLES
    assert result.stdout == ""
    assert result.stderr == "copied store 'src' to 'dst'\n"


def test_cp_store_reencrypts_with_the_same_key(cli: CliHarness) -> None:
    key = _encrypted_source(cli)

    result = cli.invoke("cp-store", "src", "dst", "-k", str(key))

    assert_exit(result, 0)
    assert cli.store().store_info("dst").key_mode is KeyMode.KEYFILE
    assert cli.store().variables("dst", key=key) == _VARIABLES
    # The ciphertext is bound to the store name, so the copy is re-encrypted (D5).
    assert _ciphertext(cli.connection, "dst") != _ciphertext(cli.connection, "src")


def test_cp_store_plain_makes_a_decrypted_copy(cli: CliHarness) -> None:
    key = _encrypted_source(cli)

    result = cli.invoke("cp-store", "src", "dst", "-k", str(key), "--plain")

    assert_exit(result, 0)
    assert not cli.store().store_info("dst").encrypted
    assert cli.store().variables("dst") == _VARIABLES
    assert cli.store().store_info("src").encrypted


def test_cp_store_encrypts_a_plaintext_copy_with_a_new_key(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    key = cli_json.key_file("new.key")

    result = cli_json.invoke("cp-store", "src", "dst", "--new-key", str(key))

    assert_exit(result, 0)
    assert cli_json.store().variables("dst", key=key) == _VARIABLES


def test_cp_store_new_key_replaces_the_source_key(cli: CliHarness) -> None:
    old = _encrypted_source(cli)
    new = cli.key_file("new.key")

    result = cli.invoke("cp-store", "src", "dst", "-k", str(old), "--new-key", str(new))

    assert_exit(result, 0)
    assert cli.store().variables("dst", key=new) == _VARIABLES
    with pytest.raises(DecryptionError):
        cli.store().variables("dst", key=old)


def test_cp_store_generates_a_new_key_file(cli: CliHarness) -> None:
    old = _encrypted_source(cli)
    new = cli.root / "generated.key"

    result = cli.invoke("cp-store", "src", "dst", "-k", str(old), "--generate-key", str(new))

    assert_exit(result, 0)
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    assert cli.store().variables("dst", key=new) == _VARIABLES


def test_cp_store_with_a_piped_passphrase(cli: CliHarness) -> None:
    old = _encrypted_source(cli)

    result = cli.invoke("cp-store", "src", "dst", "-k", str(old), "--passphrase", input="pw\n")

    assert_exit(result, 0)
    assert cli.store().store_info("dst").key_mode is KeyMode.PASSPHRASE
    assert cli.store().variables("dst", key=Passphrase(text="pw")) == _VARIABLES


def test_cp_store_asks_for_the_source_key_and_a_new_passphrase_on_a_terminal(
    cli_json: CliHarness,
) -> None:
    store = cli_json.store()
    store.create_store("src", encrypt=True, key=Passphrase(text="old"))
    store.set_many("src", _VARIABLES, key=Passphrase(text="old"))
    prompter = RecordingPrompter("old", "new")

    result = cli_json.invoke(
        "cp-store", "src", "dst", "--passphrase", stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert [kind for kind, _text in prompter.prompts] == ["secret", "new_secret"]
    assert cli_json.store().variables("dst", key=Passphrase(text="new")) == _VARIABLES


def test_cp_store_takes_the_source_key_from_the_project_file(cli_json: CliHarness) -> None:
    key = _encrypted_source(cli_json)
    cli_json.project_file(f'[keys]\nsrc = "{key.name}"\n')

    result = cli_json.invoke("cp-store", "src", "dst")

    assert_exit(result, 0)
    assert cli_json.store().variables("dst", key=key) == _VARIABLES


def test_cp_store_of_an_encrypted_store_without_a_key_fails_with_four(
    cli_json: CliHarness,
) -> None:
    _encrypted_source(cli_json)

    result = cli_json.invoke("cp-store", "src", "dst")

    assert_exit(result, 4)
    assert "-k" in result.stderr
    assert _names(cli_json) == ["src"]


def test_cp_store_with_a_wrong_key_fails_with_four(cli: CliHarness) -> None:
    _encrypted_source(cli)
    wrong = cli.key_file("wrong.key")

    result = cli.invoke("cp-store", "src", "dst", "-k", str(wrong))

    assert_exit(result, 4)
    assert _names(cli) == ["src"]


def test_cp_store_with_a_key_for_a_plaintext_source_fails_with_one(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    key = cli_json.key_file()

    result = cli_json.invoke("cp-store", "src", "dst", "-k", str(key))

    assert_exit(result, 1)
    assert "not encrypted" in result.stderr
    assert _names(cli_json) == ["src"]


def test_cp_store_of_a_missing_source_fails_with_two(cli_json: CliHarness) -> None:
    result = cli_json.invoke("cp-store", "src", "dst")

    assert_exit(result, 2)
    assert _names(cli_json) == []


def test_cp_store_onto_an_existing_store_fails_with_three_and_changes_nothing(
    cli: CliHarness,
) -> None:
    _plain_source(cli)
    cli.store().create_store("dst")
    cli.store().set("dst", "OTHER", "x")

    result = cli.invoke("cp-store", "src", "dst")

    assert_exit(result, 3)
    assert cli.store().variables("dst") == {"OTHER": "x"}


def test_cp_store_onto_an_existing_store_removes_the_generated_key_file(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)
    cli_json.store().create_store("dst")
    key = cli_json.root / "generated.key"

    result = cli_json.invoke("cp-store", "src", "dst", "--generate-key", str(key))

    assert_exit(result, 3)
    assert not key.exists()


def test_cp_store_onto_itself_without_to_fails_with_one(cli_json: CliHarness) -> None:
    _plain_source(cli_json)

    result = cli_json.invoke("cp-store", "src", "src")

    assert_exit(result, 1)
    assert "--to" in result.stderr


@pytest.mark.parametrize("dst", ["Bad", "x" * 64])
def test_cp_store_with_an_invalid_name_fails_with_one_before_generating_a_key(
    cli_json: CliHarness, dst: str
) -> None:
    _plain_source(cli_json)
    key = cli_json.root / "generated.key"

    result = cli_json.invoke("cp-store", "src", dst, "--generate-key", str(key))

    assert_exit(result, 1)
    assert not key.exists()
    assert _names(cli_json) == ["src"]


@pytest.mark.parametrize(
    "options",
    [
        ["--plain", "--passphrase"],
        ["--plain", "--new-key", "new.key"],
        ["--plain", "--generate-key", "generated.key"],
        ["--new-key", "new.key", "--passphrase"],
    ],
    ids=["plain-passphrase", "plain-new-key", "plain-generate-key", "new-key-passphrase"],
)
def test_cp_store_target_encryption_options_are_exclusive(
    cli_json: CliHarness, options: list[str]
) -> None:
    _plain_source(cli_json)
    cli_json.key_file("new.key")

    result = cli_json.invoke("cp-store", "src", "dst", *options, input="pw\n")

    assert_exit(result, 1)
    assert "only one" in result.stderr
    # cp-store calls the new key file option --new-key; -k is the source key (PD 24).
    assert "--new-key" in result.stderr
    assert _names(cli_json) == ["src"]
    assert not (cli_json.root / "generated.key").exists()


def test_cp_store_reads_stdin_only_once(cli_json: CliHarness) -> None:
    key = _encrypted_source(cli_json)

    result = cli_json.invoke(
        "cp-store", "src", "dst", "-k", "-", "--passphrase", input=key.read_text(encoding="utf-8")
    )

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert _names(cli_json) == ["src"]


def test_cp_store_new_key_from_stdin(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    key = cli_json.key_file("new.key")

    result = cli_json.invoke(
        "cp-store", "src", "dst", "--new-key", "-", input=key.read_text(encoding="utf-8")
    )

    assert_exit(result, 0)
    assert cli_json.store().variables("dst", key=key) == _VARIABLES


def test_cp_store_source_key_and_new_key_cannot_both_read_stdin(cli_json: CliHarness) -> None:
    key = _encrypted_source(cli_json)

    result = cli_json.invoke(
        "cp-store", "src", "dst", "-k", "-", "--new-key", "-", input=key.read_text(encoding="utf-8")
    )

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert _names(cli_json) == ["src"]


def test_cp_store_generate_key_to_stdout_is_refused_with_a_new_key_hint(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)

    result = cli_json.invoke("cp-store", "src", "dst", "--generate-key", "-")

    assert_exit(result, 1)
    # PD 24: the hint names cp-store's own key file option, not -k (the source key).
    assert "'--new-key -'" in result.stderr
    assert "'-k -'" not in result.stderr
    assert not (cli_json.root / "-").exists()
    assert _names(cli_json) == ["src"]


def test_cp_store_new_key_must_be_a_key_file(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    passphrase = cli_json.passphrase_file("pw\n")

    result = cli_json.invoke("cp-store", "src", "dst", "--new-key", str(passphrase))

    assert_exit(result, 4)
    assert _names(cli_json) == ["src"]


def test_cp_store_to_an_unknown_backend_fails_with_one_before_asking(cli_json: CliHarness) -> None:
    _encrypted_source(cli_json)

    result = cli_json.invoke("cp-store", "src", "dst", "--to", "nope://x", stdin_tty=True)

    assert_exit(result, 1)
    assert _names(cli_json) == ["src"]


def test_cp_store_to_another_backend(cli_json: CliHarness) -> None:
    key = _encrypted_source(cli_json)
    other = connection_for(cli_json.root / "other", "sqlite")
    (cli_json.root / "other").mkdir()

    result = cli_json.invoke("cp-store", "src", "dst", "--to", other, "-k", str(key))

    assert_exit(result, 0)
    with EnvironmentStore(other) as target:
        assert target.variables("dst", key=key) == _VARIABLES
    assert _names(cli_json) == ["src"]


def test_cp_store_to_another_backend_may_keep_the_name(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    other = connection_for(cli_json.root / "other", "sqlite")
    (cli_json.root / "other").mkdir()

    result = cli_json.invoke("cp-store", "src", "src", "--to", other)

    assert_exit(result, 0)
    with EnvironmentStore(other) as target:
        assert target.variables("src") == _VARIABLES
    assert result.stderr == "copied store 'src' to 'src'\n"


def test_cp_store_to_another_backend_that_has_the_store_fails_with_three(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)
    other = connection_for(cli_json.root / "other", "sqlite")
    (cli_json.root / "other").mkdir()
    with EnvironmentStore(other) as target:
        target.create_store("src")

    result = cli_json.invoke("cp-store", "src", "src", "--to", other)

    assert_exit(result, 3)
