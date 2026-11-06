"""`envs get`: print the winning value of a variable (spec §6.7, D16, D33, PD 23)."""

import json
from pathlib import Path

import pytest

from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _arrange(cli: CliHarness) -> Path:
    key = cli.key_file()
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"HOST": "base", "PORT": "1"})
    library.create_store("secret", encrypt=True, key=key)
    library.set_many("secret", {"HOST": "secret", "TOKEN": "t"}, key=key)
    return key


def test_get_prints_the_raw_value_without_a_newline_when_piped(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("get", "HOST", "base")

    assert_exit(result, 0)
    assert result.stdout_bytes == b"base"
    assert result.stderr == ""


def test_get_adds_a_newline_on_a_terminal(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("get", "HOST", "base", stdout_tty=True)

    assert result.stdout_bytes == b"base\n"


@pytest.mark.parametrize("value", ["line 1\nline 2\n", "a\r\nb", "trailing\r", "", "ünï ☃"])
def test_get_prints_multi_line_values_exactly(cli_json: CliHarness, value: str) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", value)

    result = cli_json.invoke("get", "X", "a")

    assert_exit(result, 0)
    assert result.stdout_bytes == value.encode("utf-8")


def test_get_prints_the_value_that_wins_the_merge(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("get", "HOST", "base", "secret", "-k", f"secret={key}")

    assert_exit(result, 0)
    assert result.stdout == "secret"


def test_get_first_wins(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("get", "HOST", "base", "secret", "-k", f"secret={key}", "--first-wins")

    assert result.stdout == "base"


def test_get_uses_the_project_store_list_and_keys(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    cli_json.project_file(f"stores = ['base', 'secret']\n[keys]\nsecret = '{key}'\n")

    result = cli_json.invoke("get", "TOKEN")

    assert_exit(result, 0)
    assert result.stdout == "t"


def test_get_prompts_for_the_key_on_a_terminal(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    prompter = RecordingPrompter(key.read_text(encoding="utf-8"))

    result = cli_json.invoke("get", "TOKEN", "secret", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert result.stdout == "t"


def test_get_without_a_key_when_not_interactive_exits_4(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("get", "TOKEN", "secret")

    assert_exit(result, 4)


def test_get_with_a_wrong_key_exits_4(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    other = cli_json.key_file("other.key")

    result = cli_json.invoke("get", "TOKEN", "secret", "-k", str(other))

    assert_exit(result, 4)
    assert result.stdout == ""


def test_get_of_a_variable_missing_in_one_store_exits_2(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("get", "NOPE", "base")

    assert_exit(result, 2)
    assert "NOPE" in result.stderr
    assert "base" in result.stderr
    assert result.stdout == ""


def test_get_of_a_variable_missing_in_every_store_names_them_all(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke("get", "NOPE", "base", "secret", "base", "-k", f"secret={key}")

    assert_exit(result, 2)
    assert "'NOPE' not found in stores: base, secret" in result.stderr


def test_get_of_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("get", "HOST", "nope")

    assert_exit(result, 2)


def test_get_validates_the_variable_name_before_prompting(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    # The default RecordingPrompter fails the test on any prompt.
    result = cli_json.invoke("get", "1BAD", "secret", stdin_tty=True)

    assert_exit(result, 1)
    assert "invalid variable name" in result.stderr


def test_get_json(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("get", "HOST", "base", "secret", "-k", f"secret={key}", "--json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {"name": "HOST", "value": "secret", "store": "secret"}
    assert result.stdout.endswith("}\n")


def test_get_without_a_key_argument_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke("get")

    assert_exit(result, 1)
