"""`envs ls`: list the merged variables of stores."""

import json
from pathlib import Path

from environment_store.config.settings import ENV_ORDERED_OVERWRITE
from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _arrange(cli: CliHarness) -> Path:
    """Plain 'base' and key file store 'secret' sharing HOST; returns the key file."""
    key = cli.key_file()
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"HOST": "base", "PORT": "1"})
    library.create_store("secret", encrypt=True, key=key)
    library.set_many("secret", {"HOST": "secret", "TOKEN": "t"}, key=key)
    return key


def test_ls_prints_the_names_sorted_one_per_line(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set_many("a", {"ZED": "1", "ALPHA": "2", "MID": "3"})

    result = cli.invoke("ls", "a")

    assert_exit(result, 0)
    assert result.stdout == "ALPHA\nMID\nZED\n"
    assert result.stderr == ""


def test_ls_of_an_empty_store_prints_nothing(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("ls", "a")

    assert_exit(result, 0)
    assert result.stdout == ""


def test_ls_with_values_prints_name_equals_value(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set_many("a", {"HOST": "localhost", "EMPTY": ""})

    result = cli.invoke("ls", "a", "-v")

    assert_exit(result, 0)
    assert result.stdout == "EMPTY=\nHOST=localhost\n"


def test_ls_with_values_shows_multi_line_values_as_json_strings(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "PEM", "line 1\nline 2\n")

    result = cli_json.invoke("ls", "a", "--values")

    assert result.stdout == 'PEM="line 1\\nline 2\\n"\n'


def test_ls_with_values_keeps_trailing_blanks_of_a_value(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "padded  ")

    result = cli_json.invoke("ls", "a", "-v")

    assert result.stdout == "X=padded  \n"


def test_ls_merges_several_stores_last_wins(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("ls", "base", "secret", "-k", f"secret={key}", "-v")

    assert_exit(result, 0)
    assert result.stdout == "HOST=secret\nPORT=1\nTOKEN=t\n"


def test_ls_first_wins(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("ls", "base", "secret", "-k", f"secret={key}", "-v", "--first-wins")

    assert result.stdout == "HOST=base\nPORT=1\nTOKEN=t\n"


def test_ls_ordered_overwrite_false_in_the_environment(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke(
        "ls", "base", "secret", "-k", f"secret={key}", "-v", env={ENV_ORDERED_OVERWRITE: "false"}
    )

    assert result.stdout.startswith("HOST=base\n")


def test_ls_ordered_overwrite_from_the_project_file(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    cli_json.project_file("ordered_overwrite = false\n")

    result = cli_json.invoke("ls", "base", "secret", "-k", f"secret={key}", "-v")

    assert result.stdout.startswith("HOST=base\n")


def test_ls_source_shows_the_winning_store_as_a_second_column(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("ls", "base", "secret", "-k", f"secret={key}", "--source")

    assert_exit(result, 0)
    assert result.stdout == "HOST   secret\nPORT   base\nTOKEN  secret\n"


def test_ls_source_with_values(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("ls", "base", "secret", "-k", f"secret={key}", "--source", "-v")

    assert result.stdout == "HOST=secret  secret\nPORT=1       base\nTOKEN=t      secret\n"


def test_ls_uses_the_project_store_list(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    cli_json.project_file(f"stores = ['base', 'secret']\n[keys]\nsecret = '{key}'\n")

    result = cli_json.invoke("ls", "-v")

    assert_exit(result, 0)
    assert result.stdout == "HOST=secret\nPORT=1\nTOKEN=t\n"


def test_positional_stores_replace_the_project_store_list(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file("stores = ['base', 'secret']\n")

    result = cli_json.invoke("ls", "base", "-v")

    assert_exit(result, 0)
    assert result.stdout == "HOST=base\nPORT=1\n"


def test_ls_without_any_store_fails(cli_json: CliHarness) -> None:
    result = cli_json.invoke("ls")

    assert_exit(result, 1)
    assert "no stores given" in result.stderr


def test_ls_of_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("ls", "nope")

    assert_exit(result, 2)
    assert "nope" in result.stderr


def test_ls_of_an_encrypted_store_with_the_key_shorthand(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("ls", "secret", "-k", str(key))

    assert_exit(result, 0)
    assert result.stdout == "HOST\nTOKEN\n"


def test_ls_of_an_encrypted_store_with_the_key_from_stdin(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("ls", "base", "secret", "-k", "secret=-", input=key.read_bytes())

    assert_exit(result, 0)
    assert result.stdout == "HOST\nPORT\nTOKEN\n"


def test_ls_of_an_encrypted_store_with_the_project_key(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    cli_json.project_file(f"[keys]\nsecret = '{key}'\n")

    result = cli_json.invoke("ls", "secret")

    assert_exit(result, 0)
    assert result.stdout == "HOST\nTOKEN\n"


def test_ls_prompts_for_a_passphrase_on_a_terminal(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("p", encrypt=True, key=Passphrase(text="pw"))
    library.set("p", "X", "1", key=Passphrase(text="pw"))
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke("ls", "p", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert result.stdout == "X\n"
    assert [kind for kind, _ in prompter.prompts] == ["secret"]


def test_ls_needs_the_key_of_an_encrypted_store_when_not_interactive(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "secret")

    assert_exit(result, 4)
    assert "-k" in result.stderr
    assert result.stdout == ""


def test_ls_with_noinput_on_a_terminal_does_not_prompt(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("--noinput", "ls", "secret", stdin_tty=True)

    assert_exit(result, 4)


def test_ls_with_a_wrong_key_exits_4(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    other = cli_json.key_file("other.key")

    result = cli_json.invoke("ls", "secret", "-k", str(other))

    assert_exit(result, 4)


def test_ls_with_a_key_for_a_plaintext_store_fails(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("ls", "base", "-k", str(key))

    assert_exit(result, 1)


def test_ls_json_lists_the_names(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("ls", "base", "--json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == [{"name": "HOST"}, {"name": "PORT"}]


def test_ls_json_with_values_and_sources(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke(
        "ls", "base", "secret", "-k", f"secret={key}", "--json", "-v", "--source"
    )

    assert_exit(result, 0)
    assert json.loads(result.stdout) == [
        {"name": "HOST", "value": "secret", "store": "secret"},
        {"name": "PORT", "value": "1", "store": "base"},
        {"name": "TOKEN", "value": "t", "store": "secret"},
    ]
    assert result.stdout.endswith("]\n")


def test_ls_json_keeps_multi_line_values_exact(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "PEM", "a\r\nb\n")

    result = cli_json.invoke("ls", "a", "--json", "-v")

    assert json.loads(result.stdout) == [{"name": "PEM", "value": "a\r\nb\n"}]


def test_ls_json_of_an_empty_store_is_an_empty_list(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("ls", "a", "--json")

    assert json.loads(result.stdout) == []


def test_ls_source_of_an_empty_store_prints_nothing(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("ls", "a", "--source")

    assert_exit(result, 0)
    assert result.stdout == ""
