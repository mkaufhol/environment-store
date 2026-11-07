"""`ENV_STORE_KEY_<STORE>` in the CLI: reading and writing commands, `run`, hints (§4.3, D53)."""

from pathlib import Path
from typing import Final

import pytest

from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_text
from tests.support.cli import CliHarness, Executed, RecordingPrompter, assert_exit

CANARY: Final = "do-not-echo-this-value"


def _key_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _arrange(cli: CliHarness) -> Path:
    """Plain 'base', key file store 'secret', passphrase store 'phrase'; returns the key file."""
    key = cli.key_file()
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"HOST": "base", "PORT": "1"})
    library.create_store("secret", encrypt=True, key=key)
    library.set_many("secret", {"HOST": "secret", "API_URL": "t"}, key=key)
    library.create_store("phrase", encrypt=True, key=Passphrase(text="pw"))
    library.set("phrase", "HOST", "phrase", key=Passphrase(text="pw"))
    return key


# --- reading commands -----------------------------------------------------------------------------


def test_ls_reads_a_keyfile_store_with_the_key_from_its_variable(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("ls", "secret", env={"ENV_STORE_KEY_SECRET": _key_text(key)})

    assert_exit(result, 0)
    assert "API_URL" in result.stdout


def test_get_reads_a_passphrase_store_with_the_passphrase_from_its_variable(
    cli_json: CliHarness,
) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("get", "HOST", "phrase", env={"ENV_STORE_KEY_PHRASE": "pw\r\n"})

    assert_exit(result, 0)
    assert result.stdout == "phrase"


def test_export_merges_stores_whose_keys_come_from_variables(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    env = {"ENV_STORE_KEY_SECRET": _key_text(key), "ENV_STORE_KEY_PHRASE": "pw"}

    result = cli_json.invoke("export", "base", "secret", "phrase", "-t", "json", env=env)

    assert_exit(result, 0)
    assert '"HOST": "phrase"' in result.stdout
    assert '"API_URL": "t"' in result.stdout


def test_the_variable_beats_the_project_key_and_the_prompt(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    wrong = cli_json.key_file("wrong.key")
    cli_json.project_file(f"[keys]\nsecret = '{wrong}'\n")

    result = cli_json.invoke(
        "ls",
        "secret",
        env={"ENV_STORE_KEY_SECRET": _key_text(key)},
        connection=True,
        stdin_tty=True,
    )

    assert_exit(result, 0)
    assert "API_URL" in result.stdout


def test_k_beats_a_broken_variable(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("ls", "secret", "-k", str(key), env={"ENV_STORE_KEY_SECRET": ""})

    assert_exit(result, 0)


def test_a_wrong_key_in_the_variable_is_a_decryption_error(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "secret", env={"ENV_STORE_KEY_SECRET": generate_key_text()})

    assert_exit(result, 4)
    assert "decrypt" in result.stderr.lower()


@pytest.mark.parametrize("value", ["", "\n"])
def test_an_empty_variable_exits_4_naming_it(cli_json: CliHarness, value: str) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "secret", env={"ENV_STORE_KEY_SECRET": value})

    assert_exit(result, 4)
    assert "ENV_STORE_KEY_SECRET" in result.stderr
    assert "empty" in result.stderr


def test_invalid_key_text_exits_4_naming_the_variable_but_not_the_value(
    cli_json: CliHarness,
) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "secret", env={"ENV_STORE_KEY_SECRET": CANARY})

    assert_exit(result, 4)
    assert "ENV_STORE_KEY_SECRET" in result.stderr
    assert "envs keygen" in result.stderr
    assert CANARY not in result.stderr + result.stdout


def test_key_text_for_a_passphrase_store_names_the_variable_not_k(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "phrase", env={"ENV_STORE_KEY_PHRASE": generate_key_text()})

    assert_exit(result, 4)
    assert "ENV_STORE_KEY_PHRASE" in result.stderr
    assert "-k" not in result.stderr


def test_variables_of_plaintext_and_unused_stores_are_ignored(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    env = {"ENV_STORE_KEY_BASE": CANARY, "ENV_STORE_KEY_PHRASE": "", "ENV_STORE_KEY_X": ""}

    result = cli_json.invoke("ls", "base", env=env)

    assert_exit(result, 0)


def test_colliding_stores_with_a_set_variable_exit_1_before_any_key_is_read(
    cli_json: CliHarness,
) -> None:
    library = cli_json.store()
    library.create_store("my-app", encrypt=True, key=Passphrase(text="a"))
    library.create_store("my_app", encrypt=True, key=Passphrase(text="b"))
    prompter = RecordingPrompter()

    result = cli_json.invoke(
        "ls",
        "my-app",
        "my_app",
        env={"ENV_STORE_KEY_MY_APP": "a"},
        stdin_tty=True,
        prompter=prompter,
    )

    assert_exit(result, 1)
    assert "'my-app'" in result.stderr
    assert "'my_app'" in result.stderr
    assert "ENV_STORE_KEY_MY_APP" in result.stderr
    assert prompter.prompts == []


def test_k_for_both_colliding_stores_avoids_the_collision(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("my-app", encrypt=True, key=Passphrase(text="a"))
    library.create_store("my_app", encrypt=True, key=Passphrase(text="b"))
    first = cli_json.passphrase_file("a", "a.txt")
    second = cli_json.passphrase_file("b", "b.txt")

    result = cli_json.invoke(
        "ls",
        "my-app",
        "my_app",
        "-k",
        f"my-app={first}",
        "-k",
        f"my_app={second}",
        env={"ENV_STORE_KEY_MY_APP": "a"},
    )

    assert_exit(result, 0)


# --- hints ----------------------------------------------------------------------------------------


def test_a_missing_key_with_noinput_names_the_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("--noinput", "ls", "secret")

    assert_exit(result, 4)
    assert "-k <path>" in result.stderr
    assert "ENV_STORE_KEY_SECRET" in result.stderr


def test_a_missing_key_among_several_stores_names_its_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "base", "phrase", "secret")

    assert_exit(result, 4)
    assert "-k phrase=<path>" in result.stderr
    assert "ENV_STORE_KEY_PHRASE" in result.stderr


# --- writing commands -----------------------------------------------------------------------------


def test_set_takes_the_key_from_the_variable(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke(
        "set", "-s", "secret", "NEW", input="v", env={"ENV_STORE_KEY_SECRET": _key_text(key)}
    )

    assert_exit(result, 0)
    assert cli.store().get("secret", "NEW", key=key) == "v"


def test_rm_takes_the_passphrase_from_the_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("rm", "-s", "phrase", "HOST", env={"ENV_STORE_KEY_PHRASE": "pw"})

    assert_exit(result, 0)
    assert cli_json.store().variables("phrase", key=Passphrase(text="pw")) == {}


def test_import_of_an_empty_document_still_checks_the_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    path = cli_json.root / "empty.env"
    path.write_text("", encoding="utf-8")

    result = cli_json.invoke(
        "import", "-s", "phrase", "-f", str(path), env={"ENV_STORE_KEY_PHRASE": ""}
    )

    assert_exit(result, 4)
    assert "ENV_STORE_KEY_PHRASE" in result.stderr


def test_rekey_takes_the_old_key_from_the_variable(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    new = cli_json.key_file("new.key")

    result = cli_json.invoke(
        "rekey", "-s", "secret", "--new-key", str(new), env={"ENV_STORE_KEY_SECRET": _key_text(key)}
    )

    assert_exit(result, 0)
    assert cli_json.store().get("secret", "API_URL", key=new) == "t"


def test_rekey_never_takes_the_new_key_from_the_variable(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("rekey", "-s", "secret", env={"ENV_STORE_KEY_SECRET": _key_text(key)})

    assert_exit(result, 1)
    assert "--new-key" in result.stderr


def test_create_store_encrypt_never_takes_the_key_from_the_variable(cli_json: CliHarness) -> None:
    result = cli_json.invoke(
        "create-store", "fresh", "-e", env={"ENV_STORE_KEY_FRESH": generate_key_text()}
    )

    assert_exit(result, 1)
    assert cli_json.store().list_stores() == []


def test_encrypt_never_takes_the_key_from_the_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke(
        "encrypt", "-s", "base", env={"ENV_STORE_KEY_BASE": generate_key_text()}
    )

    assert_exit(result, 1)
    assert not cli_json.store().store_info("base").encrypted


def test_cp_store_takes_the_source_key_but_not_a_new_key_from_variables(
    cli_json: CliHarness,
) -> None:
    key = _arrange(cli_json)
    env = {"ENV_STORE_KEY_SECRET": _key_text(key), "ENV_STORE_KEY_COPY": generate_key_text()}

    result = cli_json.invoke("cp-store", "secret", "copy", env=env)

    assert_exit(result, 0)
    # "same" encryption: the copy keeps the source's key, not the copy's variable.
    assert cli_json.store().get("copy", "API_URL", key=key) == "t"


def test_mv_store_takes_the_source_key_from_its_variable(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("mv-store", "phrase", "moved", env={"ENV_STORE_KEY_PHRASE": "pw"})

    assert_exit(result, 0)
    assert cli_json.store().get("moved", "HOST", key=Passphrase(text="pw")) == "phrase"


# --- run ------------------------------------------------------------------------------------------


def test_run_strips_every_key_variable_from_the_child(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    env = {
        "ENV_STORE_KEY_SECRET": _key_text(key),
        "ENV_STORE_KEY_UNUSED": "x",
        "ENV_STORE_KEYS": "kept",
        "OTHER": "kept",
    }

    result = cli_json.invoke("run", "secret", "--", "cmd", env=env)

    assert isinstance(result.exception, Executed)
    _, _, child = cli_json.exec_calls[0]
    assert child["API_URL"] == "t"
    assert child["OTHER"] == "kept"
    assert child["ENV_STORE_KEYS"] == "kept"
    assert not [name for name in child if name.startswith("ENV_STORE_KEY_")]


def test_run_strips_key_variables_also_when_no_store_used_them(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("run", "base", "--", "cmd", env={"ENV_STORE_KEY_PROD": "x"})

    assert isinstance(result.exception, Executed)
    _, _, child = cli_json.exec_calls[0]
    assert "ENV_STORE_KEY_PROD" not in child
    assert child["HOST"] == "base"
