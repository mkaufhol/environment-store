"""Merged output order (D52) in every CLI output: `ls`, `export`, `export-shell` and `run`.

The stores' variables come in load order, each store's sorted by name; a variable shared by
several stores keeps its first position and takes the value of the merge order.
"""

import json
from typing import Final

import pytest

from tests.support.cli import CliHarness, assert_exit

_NAMES: Final = ("DEBUG", "ENV", "DB_NAME")
_LAST_WINS_DOTENV: Final = "DEBUG=True\nENV=staging\nDB_NAME=test\n"
_FIRST_WINS_DOTENV: Final = "DEBUG=True\nENV=development\nDB_NAME=test\n"


def _arrange(cli: CliHarness) -> None:
    """The user's example of D52: store-a and store-b share ENV."""
    library = cli.store()
    library.create_store("store-a")
    library.set_many("store-a", {"ENV": "development", "DEBUG": "True"})
    library.create_store("store-b")
    library.set_many("store-b", {"ENV": "staging", "DB_NAME": "test"})


# --- export -----------------------------------------------------------------------------------


def test_export_dotenv_follows_the_store_order(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == _LAST_WINS_DOTENV


def test_export_dotenv_first_wins_keeps_the_order_and_the_first_value(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export", "--first-wins", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == _FIRST_WINS_DOTENV


def test_export_json_follows_the_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "-t", "json", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == ('{\n  "DEBUG": "True",\n  "ENV": "staging",\n  "DB_NAME": "test"\n}\n')


def test_export_toml_follows_the_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "-t", "toml", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == 'DEBUG = "True"\nENV = "staging"\nDB_NAME = "test"\n'


@pytest.mark.parametrize("fmt", ["json", "toml"])
def test_export_first_wins_keeps_the_order_in_json_and_toml(cli_json: CliHarness, fmt: str) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "--first-wins", "-t", fmt, "store-a", "store-b")

    assert_exit(result, 0)
    positions = [result.stdout.index(f'"{name}"' if fmt == "json" else name) for name in _NAMES]
    assert positions == sorted(positions)
    assert "development" in result.stdout
    assert "staging" not in result.stdout


def test_export_to_a_file_follows_the_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "-f", ".env", "store-a", "store-b")

    assert_exit(result, 0)
    assert (cli_json.root / ".env").read_text(encoding="utf-8") == _LAST_WINS_DOTENV


def test_export_nested_keeps_the_store_order_each_store_sorted(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "--nested", "store-b", "store-a")

    assert_exit(result, 0)
    assert result.stdout == (
        "STORE_B__DB_NAME=test\nSTORE_B__ENV=staging\n"
        "STORE_A__DEBUG=True\nSTORE_A__ENV=development\n"
    )


# --- ls -----------------------------------------------------------------------------------------


def test_ls_follows_the_store_order(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("ls", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == "DEBUG\nENV\nDB_NAME\n"


def test_ls_values_follow_the_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "-v", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == _LAST_WINS_DOTENV


def test_ls_values_first_wins_keep_the_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "-v", "--first-wins", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == _FIRST_WINS_DOTENV


def test_ls_source_follows_the_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "--source", "store-a", "store-b")

    assert_exit(result, 0)
    assert [line.split() for line in result.stdout.splitlines()] == [
        ["DEBUG", "store-a"],
        ["ENV", "store-b"],
        ["DB_NAME", "store-b"],
    ]


def test_ls_json_lists_the_variables_in_store_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("ls", "--json", "-v", "--source", "store-a", "store-b")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == [
        {"name": "DEBUG", "store": "store-a", "value": "True"},
        {"name": "ENV", "store": "store-b", "value": "staging"},
        {"name": "DB_NAME", "store": "store-b", "value": "test"},
    ]


# --- export-shell and run -----------------------------------------------------------------------


def test_export_shell_follows_the_store_order(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export-shell", "-o", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == "export DEBUG=True\nexport ENV=staging\nexport DB_NAME=test\n"


def test_export_shell_first_wins_keeps_the_order(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export-shell", "-o", "--first-wins", "store-a", "store-b")

    assert_exit(result, 0)
    assert result.stdout == "export DEBUG=True\nexport ENV=development\nexport DB_NAME=test\n"


def test_run_adds_the_variables_in_store_order(
    cli_json: CliHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _NAMES:
        monkeypatch.delenv(name, raising=False)
    _arrange(cli_json)

    cli_json.invoke("run", "store-a", "store-b", "--", "app")

    assert len(cli_json.exec_calls) == 1
    _, _, env = cli_json.exec_calls[0]
    assert [name for name in env if name in _NAMES] == list(_NAMES)
    assert env["ENV"] == "staging"
