"""`envs rekey` and `envs encrypt`: new secrets for stores."""

import json
import stat
from pathlib import Path

import pytest

from environment_store.core.errors import BackendError
from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, raising


def _keyfile_store(cli: CliHarness, name: str = "a") -> Path:
    key = cli.key_file()
    library = cli.store()
    library.create_store(name, encrypt=True, key=key)
    library.set_many(name, {"HOST": "h", "TOKEN": "t"}, key=key)
    return key


def _salt(cli: CliHarness, store: str) -> str:
    document = json.loads((cli.root / "stores" / f"{store}.json").read_text(encoding="utf-8"))
    salt: str = document["cipher"]["kdf"]["salt"]
    return salt


# --- rekey ----------------------------------------------------------------------------------------


def test_rekey_keyfile_to_passphrase_to_keyfile(cli: CliHarness) -> None:
    old = _keyfile_store(cli)

    to_passphrase = cli.invoke("rekey", "-s", "a", "-k", str(old), "--passphrase", input="pw\n")
    new_key = cli.key_file("new.key")
    to_keyfile = cli.invoke(
        "rekey", "-s", "a", "-k", str(cli.passphrase_file("pw\n")), "--new-key", str(new_key)
    )

    assert_exit(to_passphrase, 0)
    assert_exit(to_keyfile, 0)
    library = cli.store()
    assert library.variables("a", key=new_key) == {"HOST": "h", "TOKEN": "t"}
    assert "rekeyed store 'a'" in to_keyfile.stderr


def test_after_rekey_the_old_key_no_longer_works(cli: CliHarness) -> None:
    old = _keyfile_store(cli)
    new_key = cli.key_file("new.key")

    result = cli.invoke("rekey", "-s", "a", "-k", str(old), "--new-key", str(new_key))

    assert_exit(result, 0)
    # `export` reads like `ls`; both need the store's current key.
    assert_exit(cli.invoke("export", "a", "-k", str(old)), 4)


def test_rekey_with_a_passphrase_uses_a_new_salt(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a", encrypt=True, key=Passphrase(text="old"))
    library.set("a", "X", "1", key=Passphrase(text="old"))
    before = _salt(cli_json, "a")

    result = cli_json.invoke(
        "rekey", "-s", "a", "-k", str(cli_json.passphrase_file("old")), "--passphrase", input="new"
    )

    assert_exit(result, 0)
    assert _salt(cli_json, "a") != before
    assert cli_json.store().get("a", "X", key=Passphrase(text="new")) == "1"


def test_rekey_prompts_for_the_old_and_the_new_secret_on_a_terminal(
    cli_json: CliHarness,
) -> None:
    library = cli_json.store()
    library.create_store("a", encrypt=True, key=Passphrase(text="old"))
    library.set("a", "X", "1", key=Passphrase(text="old"))
    prompter = RecordingPrompter("old", "new")

    result = cli_json.invoke("rekey", "-s", "a", "--passphrase", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert [kind for kind, _ in prompter.prompts] == ["secret", "new_secret"]
    assert cli_json.store().get("a", "X", key=Passphrase(text="new")) == "1"


def test_rekey_uses_the_project_key(cli_json: CliHarness) -> None:
    old = _keyfile_store(cli_json)
    cli_json.project_file(f'[keys]\na = "{old.name}"\n')
    new_key = cli_json.key_file("new.key")

    result = cli_json.invoke("rekey", "-s", "a", "--new-key", str(new_key))

    assert_exit(result, 0)
    assert cli_json.store().get("a", "HOST", key=new_key) == "h"


def test_rekey_generate_key_writes_a_0600_key_file_that_decrypts_the_store(
    cli: CliHarness,
) -> None:
    old = _keyfile_store(cli)
    generated = cli.root / "gen.key"

    result = cli.invoke("rekey", "-s", "a", "-k", str(old), "--generate-key", str(generated))

    assert_exit(result, 0)
    assert stat.S_IMODE(generated.stat().st_mode) == 0o600
    assert cli.store().get("a", "TOKEN", key=generated) == "t"


def test_rekey_new_key_from_stdin(cli_json: CliHarness) -> None:
    old = _keyfile_store(cli_json)
    new_key = cli_json.key_file("new.key")

    result = cli_json.invoke(
        "rekey", "-s", "a", "-k", str(old), "--new-key", "-",
        input=new_key.read_bytes(),
    )  # fmt: skip

    assert_exit(result, 0)
    assert cli_json.store().get("a", "TOKEN", key=new_key) == "t"


def test_rekey_with_a_wrong_old_key_exits_4_and_removes_the_generated_file(
    cli_json: CliHarness,
) -> None:
    _keyfile_store(cli_json)
    wrong = cli_json.key_file("wrong.key")
    generated = cli_json.root / "gen.key"

    result = cli_json.invoke("rekey", "-s", "a", "-k", str(wrong), "--generate-key", str(generated))

    assert_exit(result, 4)
    assert not generated.exists()


def test_rekey_generate_key_after_a_failed_commit_keeps_the_file(cli_json: CliHarness) -> None:
    old = _keyfile_store(cli_json)
    generated = cli_json.root / "gen.key"
    opener = cli_json.hooked_opener(after={"write_store": raising(BackendError("connection lost"))})

    result = cli_json.invoke(
        "rekey", "-s", "a", "-k", str(old), "--generate-key", str(generated), opener=opener
    )

    assert_exit(result, 1)
    assert generated.exists()
    assert str(generated) in result.stderr
    assert cli_json.store().get("a", "TOKEN", key=generated) == "t"


def test_rekey_of_a_concurrently_changed_store_exits_5(cli_json: CliHarness) -> None:
    old = _keyfile_store(cli_json)
    generated = cli_json.root / "gen.key"

    def change() -> None:
        cli_json.store().set("a", "RACE", "1", key=old)

    opener = cli_json.hooked_opener(before={"write_store": change})

    result = cli_json.invoke(
        "rekey", "-s", "a", "-k", str(old), "--generate-key", str(generated), opener=opener
    )

    assert_exit(result, 5)
    assert not generated.exists()


def test_rekey_of_a_plaintext_store_exits_1_before_generating(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    generated = cli_json.root / "gen.key"

    result = cli_json.invoke("rekey", "-s", "a", "--generate-key", str(generated))

    assert_exit(result, 1)
    assert "not encrypted" in result.stderr
    assert "envs encrypt" in result.stderr
    assert not generated.exists()


def test_rekey_with_a_key_for_a_plaintext_store_exits_1(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke(
        "rekey", "-s", "a", "-k", str(cli_json.key_file()), "--passphrase", input="x"
    )

    assert_exit(result, 1)


def test_rekey_of_a_missing_store_exits_2_without_a_prompt(cli_json: CliHarness) -> None:
    result = cli_json.invoke("rekey", "-s", "nope", "--passphrase", stdin_tty=True)

    assert_exit(result, 2)


def test_rekey_needs_a_new_secret_option_before_any_prompt(cli_json: CliHarness) -> None:
    _keyfile_store(cli_json)

    result = cli_json.invoke("rekey", "-s", "a", stdin_tty=True)

    assert_exit(result, 1)
    assert "--new-key" in result.stderr
    assert "--passphrase" in result.stderr


def test_rekey_with_two_new_secret_options_exits_1_before_any_prompt(
    cli_json: CliHarness,
) -> None:
    _keyfile_store(cli_json)

    result = cli_json.invoke(
        "rekey", "-s", "a", "--passphrase", "--new-key", "x.key", stdin_tty=True
    )

    assert_exit(result, 1)
    assert "only one" in result.stderr


@pytest.mark.parametrize("command", ["rekey", "encrypt"])
def test_generate_key_dash_is_refused_and_creates_no_file(
    cli_json: CliHarness, command: str
) -> None:
    _keyfile_store(cli_json)
    cli_json.store().create_store("p")
    store = "a" if command == "rekey" else "p"
    key = ["-k", str(cli_json.root / "a.key")] if command == "rekey" else []

    result = cli_json.invoke(command, "-s", store, *key, "--generate-key", "-")

    assert_exit(result, 1)
    assert "envs keygen -" in result.stderr
    assert not (cli_json.root / "-").exists()


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--generate-key", "-"], "envs keygen -"),
        (["--generate-key", ""], "--generate-key needs a file path"),
        (["--generate-key", "existing.key"], "already exists"),
        (["--new-key", ""], "--new-key is empty"),
    ],
)
def test_rekey_refuses_an_unusable_new_secret_option_before_asking_for_the_old_secret(
    cli_json: CliHarness, options: list[str], message: str
) -> None:
    cli_json.store().create_store("e", encrypt=True, key=Passphrase(text="pw"))
    existing = cli_json.root / "existing.key"
    existing.write_text("keep", encoding="utf-8")
    options = [str(existing) if option == "existing.key" else option for option in options]
    prompter = RecordingPrompter()

    result = cli_json.invoke("rekey", "-s", "e", *options, stdin_tty=True, prompter=prompter)

    assert_exit(result, 1)
    assert message in result.stderr
    assert prompter.prompts == []
    assert existing.read_text(encoding="utf-8") == "keep"
    assert not (cli_json.root / "-").exists()


def test_rekey_with_two_stdin_consumers_exits_1(cli_json: CliHarness) -> None:
    old = _keyfile_store(cli_json)

    result = cli_json.invoke("rekey", "-s", "a", "-k", "-", "--passphrase", input=old.read_bytes())

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert cli_json.store().get("a", "TOKEN", key=old) == "t"


def test_rekey_invalid_store_name_exits_1(cli_json: CliHarness) -> None:
    result = cli_json.invoke("rekey", "-s", "Bad Name", "--passphrase")

    assert_exit(result, 1)


# --- encrypt --------------------------------------------------------------------------------------


def test_encrypt_turns_a_plain_store_into_an_encrypted_one(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set("a", "X", "1")
    key = cli.key_file()

    result = cli.invoke("encrypt", "-s", "a", "--new-key", str(key))

    assert_exit(result, 0)
    assert "encrypted store 'a'" in result.stderr
    # Even the names need the key now, as the whole store is one encrypted blob; `export`
    # reads like `ls`.
    assert_exit(cli.invoke("export", "a"), 4)
    listed = cli.invoke("export", "a", "-k", str(key))
    assert_exit(listed, 0)
    assert listed.stdout == "X=1\n"


def test_encrypt_with_a_piped_passphrase(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "1")

    result = cli_json.invoke("encrypt", "-s", "a", "--passphrase", input="pw\n")

    assert_exit(result, 0)
    assert cli_json.store().get("a", "X", key=Passphrase(text="pw")) == "1"


def test_encrypt_with_a_prompted_passphrase(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke(
        "encrypt", "-s", "a", "--passphrase", stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert [kind for kind, _ in prompter.prompts] == ["new_secret"]
    assert cli_json.store().store_info("a").encrypted


def test_encrypt_generate_key(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "1")
    generated = cli_json.root / "gen.key"

    result = cli_json.invoke("encrypt", "-s", "a", "--generate-key", str(generated))

    assert_exit(result, 0)
    assert stat.S_IMODE(generated.stat().st_mode) == 0o600
    assert cli_json.store().get("a", "X", key=generated) == "1"


def test_encrypt_twice_exits_1_before_generating(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    first = cli_json.invoke("encrypt", "-s", "a", "--passphrase", input="pw")
    generated = cli_json.root / "gen.key"

    second = cli_json.invoke("encrypt", "-s", "a", "--generate-key", str(generated))

    assert_exit(first, 0)
    assert_exit(second, 1)
    assert "already encrypted" in second.stderr
    assert not generated.exists()


def test_encrypt_of_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    generated = cli_json.root / "gen.key"

    result = cli_json.invoke("encrypt", "-s", "nope", "--generate-key", str(generated))

    assert_exit(result, 2)
    assert not generated.exists()


def test_encrypt_needs_a_new_secret_option(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("encrypt", "-s", "a")

    assert_exit(result, 1)
    assert "--generate-key" in result.stderr


def test_encrypt_noinput_with_passphrase_on_a_terminal_exits_4(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke(
        "--noinput", "encrypt", "-s", "a", "--passphrase", stdin_tty=True, input="never read"
    )

    assert_exit(result, 4)
    assert not cli_json.store().store_info("a").encrypted


def test_encrypt_after_a_failed_commit_keeps_the_generated_file(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "1")
    generated = cli_json.root / "gen.key"
    opener = cli_json.hooked_opener(after={"write_store": raising(BackendError("lost"))})

    result = cli_json.invoke("encrypt", "-s", "a", "--generate-key", str(generated), opener=opener)

    assert_exit(result, 1)
    assert str(generated) in result.stderr
    assert cli_json.store().get("a", "X", key=generated) == "1"


def test_encrypt_with_a_file_that_is_not_a_key_file_exits_4(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("encrypt", "-s", "a", "--new-key", str(cli_json.passphrase_file("pw")))

    assert_exit(result, 4)
    assert not cli_json.store().store_info("a").encrypted
