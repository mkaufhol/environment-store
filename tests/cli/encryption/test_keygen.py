"""`envs keygen`: key files and printed keys (spec §4.5, D4, D33, PD 10, PD 17)."""

import re
import stat
from typing import Final

import pytest

from tests.support.cli import CliHarness, assert_exit

_KEY_LINE: Final = re.compile(r"envstore-key-v1:[A-Za-z0-9_-]{43}\n")


def test_keygen_writes_a_key_file_with_mode_0600(cli_json: CliHarness) -> None:
    target = cli_json.root / "new.key"

    result = cli_json.invoke("keygen", str(target))

    assert_exit(result, 0)
    assert _KEY_LINE.fullmatch(target.read_text(encoding="utf-8"))
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert result.stdout == ""
    assert str(target) in result.stderr


def test_generated_key_file_encrypts_a_store(cli_json: CliHarness) -> None:
    target = cli_json.root / "new.key"
    cli_json.invoke("keygen", str(target))
    library = cli_json.store()

    library.create_store("a", encrypt=True, key=target)
    library.set("a", "X", "1", key=target)

    assert library.get("a", "X", key=target) == "1"


def test_keygen_never_overwrites_an_existing_file(cli_json: CliHarness) -> None:
    target = cli_json.root / "existing.key"
    target.write_text("keep", encoding="utf-8")

    result = cli_json.invoke("keygen", str(target))

    assert_exit(result, 1)
    assert str(target) in result.stderr
    assert target.read_text(encoding="utf-8") == "keep"


def test_keygen_dash_prints_the_key_line_to_stdout(cli_json: CliHarness) -> None:
    result = cli_json.invoke("keygen", "-")

    assert_exit(result, 0)
    assert _KEY_LINE.fullmatch(result.stdout)
    assert result.stderr == ""
    assert not (cli_json.root / "-").exists()


def test_keygen_prints_a_new_key_each_time(cli_json: CliHarness) -> None:
    first = cli_json.invoke("keygen", "-")
    second = cli_json.invoke("keygen", "-")

    assert first.stdout != second.stdout


def test_keygen_needs_no_connection(cli_json: CliHarness) -> None:
    result = cli_json.invoke("keygen", "-", connection=False)

    assert_exit(result, 0)
    assert _KEY_LINE.fullmatch(result.stdout)


def test_keygen_opens_no_store(cli_json: CliHarness) -> None:
    result = cli_json.invoke("keygen", str(cli_json.root / "k.key"))

    assert_exit(result, 0)
    assert not (cli_json.root / "stores").exists()


@pytest.mark.parametrize(
    "project",
    [
        "stores = [\n",
        "unknown_key = 1\n",
        "connection = 'postgresql://user:hunter2@db.example/envs'\n",
    ],
    ids=["bad-toml", "unknown-key", "password-in-connection"],
)
def test_keygen_ignores_the_project_file(cli_json: CliHarness, project: str) -> None:
    # D44: a broken .envstore.toml cannot stop keygen, and it prints no warning either.
    cli_json.project_file(project)

    result = cli_json.invoke("keygen", "-", connection=False)

    assert_exit(result, 0)
    assert _KEY_LINE.fullmatch(result.stdout)
    assert result.stderr == ""


def test_keygen_ignores_the_connection(cli_json: CliHarness) -> None:
    result = cli_json.invoke("-c", "", "keygen", "-", connection=False)

    assert_exit(result, 0)
    assert _KEY_LINE.fullmatch(result.stdout)


def test_keygen_without_a_path_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke("keygen")

    assert_exit(result, 1)


def test_keygen_with_an_empty_path_names_the_problem(cli_json: CliHarness) -> None:
    result = cli_json.invoke("keygen", "")

    assert_exit(result, 1)
    assert "needs a file path" in result.stderr
    assert "'.'" not in result.stderr


def test_keygen_into_a_missing_directory_fails_with_the_path(cli_json: CliHarness) -> None:
    target = cli_json.root / "missing" / "k.key"

    result = cli_json.invoke("keygen", str(target))

    assert_exit(result, 1)
    assert str(target) in result.stderr
    assert "Traceback" not in result.stderr
