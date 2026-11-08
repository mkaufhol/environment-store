"""`envs export`: formats, files, nested mode, refusals and keys."""

import json
import stat
import tomllib
from collections.abc import Callable

import pytest

from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _dotenv_lines(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines())


def _arrange(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"DB_HOST": "localhost", "PORT": "5432"})
    library.create_store("customer-a")
    library.set_many("customer-a", {"DB_HOST": "10.0.0.5"})


# --- formats and destinations -------------------------------------------------------------------


def test_export_without_options_writes_dotenv_to_stdout(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export", "base", "customer-a")

    assert_exit(result, 0)
    assert result.stdout == "DB_HOST=10.0.0.5\nPORT=5432\n"
    assert result.stderr == ""


def test_export_dash_file_writes_to_stdout(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export", "base", "-f", "-", "-t", "json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {"DB_HOST": "localhost", "PORT": "5432"}


@pytest.mark.parametrize("fmt", ["json", "toml", "dotenv"])
def test_export_type_to_stdout(cli: CliHarness, fmt: str) -> None:
    _arrange(cli)

    result = cli.invoke("export", "base", "-t", fmt)

    assert_exit(result, 0)
    expected = {"DB_HOST": "localhost", "PORT": "5432"}
    if fmt == "json":
        assert json.loads(result.stdout) == expected
    elif fmt == "toml":
        assert tomllib.loads(result.stdout) == expected
    else:
        assert result.stdout == "DB_HOST=localhost\nPORT=5432\n"


@pytest.mark.parametrize(
    ("name", "parse"),
    [
        (".env", _dotenv_lines),
        (".env.local", _dotenv_lines),
        ("out.json", json.loads),
        ("out.toml", tomllib.loads),
    ],
)
def test_export_infers_the_format_from_the_file_name(
    cli: CliHarness, name: str, parse: Callable[[str], object]
) -> None:
    _arrange(cli)

    result = cli.invoke("export", "base", "-f", name)

    assert_exit(result, 0)
    text = (cli.root / name).read_text(encoding="utf-8")
    assert parse(text) == {"DB_HOST": "localhost", "PORT": "5432"}
    assert result.stdout == ""
    assert name in result.stderr


def test_export_type_overrides_the_file_name(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "base", "-f", "out.txt", "-t", "json")

    assert_exit(result, 0)
    assert json.loads((cli_json.root / "out.txt").read_text(encoding="utf-8")) == {
        "DB_HOST": "localhost",
        "PORT": "5432",
    }


def test_export_to_an_unknown_extension_without_type_fails_before_loading(
    cli_json: CliHarness,
) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=Passphrase(text="pw"))

    result = cli_json.invoke("export", "secret", "-f", "out.txt", stdin_tty=True)

    assert_exit(result, 1)
    assert "out.txt" in result.stderr
    assert "-t" in result.stderr
    assert not (cli_json.root / "out.txt").exists()


def test_exported_file_has_mode_0600(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "base", "-f", ".env")

    assert_exit(result, 0)
    assert stat.S_IMODE((cli_json.root / ".env").stat().st_mode) == 0o600


def test_existing_output_file_is_refused_and_unchanged(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    target = cli_json.root / ".env"
    target.write_text("KEEP=1\n", encoding="utf-8")

    result = cli_json.invoke("export", "base", "-f", ".env")

    assert_exit(result, 1)
    assert "--force" in result.stderr
    assert "force=True" not in result.stderr
    assert target.read_text(encoding="utf-8") == "KEEP=1\n"


def test_force_replaces_an_existing_output_file(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    target = cli_json.root / ".env"
    target.write_text("KEEP=1\n", encoding="utf-8")

    result = cli_json.invoke("export", "base", "-f", ".env", "--force")

    assert_exit(result, 0)
    assert target.read_text(encoding="utf-8") == "DB_HOST=localhost\nPORT=5432\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_force_with_stdout_is_accepted_and_has_no_effect(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "base", "--force")

    assert_exit(result, 0)
    assert result.stdout == "DB_HOST=localhost\nPORT=5432\n"


def test_export_into_a_missing_directory_fails_with_the_path(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    target = cli_json.root / "missing" / ".env"

    result = cli_json.invoke("export", "base", "-f", str(target))

    assert_exit(result, 1)
    assert str(target) in result.stderr
    assert "Traceback" not in result.stderr
    assert not (cli_json.root / "missing").exists()


def test_unknown_type_is_a_usage_error(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "base", "-t", "yaml")

    assert_exit(result, 1)
    assert result.stdout == ""


# --- golden output --------------------------------------------------------------------------------


def test_nested_json_matches_the_golden_output(cli: CliHarness) -> None:
    _arrange(cli)
    cli.store().delete("base", ["PORT"])

    result = cli.invoke("export", "--nested", "-t", "json", "base", "customer-a")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {
        "base": {"DB_HOST": "localhost"},
        "customer-a": {"DB_HOST": "10.0.0.5"},
    }
    assert list(json.loads(result.stdout)) == ["base", "customer-a"]


def test_nested_dotenv_matches_the_golden_output(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("base_conf")
    library.set("base_conf", "DB_HOST", "localhost")
    library.create_store("customer_a")
    library.set("customer_a", "DB_HOST", "10.0.0.5")

    result = cli.invoke("export", "--nested", "-t", "dotenv", "base_conf", "customer_a")

    assert_exit(result, 0)
    assert result.stdout == "BASE_CONF__DB_HOST=localhost\nCUSTOMER_A__DB_HOST=10.0.0.5\n"


def test_nested_toml_has_one_table_per_store(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export", "--nested", "-f", "out.toml", "base", "customer-a")

    assert_exit(result, 0)
    text = (cli_json.root / "out.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text) == {
        "base": {"DB_HOST": "localhost", "PORT": "5432"},
        "customer-a": {"DB_HOST": "10.0.0.5"},
    }


def test_nested_dotenv_collision_fails_and_writes_no_file(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a-b")
    library.set("a-b", "X", "1")
    library.create_store("a_b")
    library.set("a_b", "X", "2")

    result = cli_json.invoke("export", "--nested", "-f", ".env", "a-b", "a_b")

    assert_exit(result, 1)
    assert "A_B__X" in result.stderr
    assert not (cli_json.root / ".env").exists()


# --- merge order ----------------------------------------------------------------------------------


def test_first_wins_keeps_the_first_store(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export", "--first-wins", "base", "customer-a")

    assert_exit(result, 0)
    assert result.stdout == "DB_HOST=localhost\nPORT=5432\n"


def test_project_store_list_is_the_default(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file('stores = ["customer-a", "base"]\n')

    result = cli_json.invoke("export")

    assert_exit(result, 0)
    assert result.stdout == "DB_HOST=localhost\nPORT=5432\n"


# --- dotenv refusals: values python-dotenv or Compose would interpolate ---------------------------


@pytest.mark.parametrize("value", ["${HOME}", "it's $HOME", 'a "$x"\nb'])
def test_dotenv_refusals_fail_with_a_hint_and_write_no_file(
    cli_json: CliHarness, value: str
) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "V", value)

    result = cli_json.invoke("export", "a", "-f", ".env")

    assert_exit(result, 1)
    assert "-t json" in result.stderr
    assert "fmt=" not in result.stderr
    assert value not in result.stderr
    assert not (cli_json.root / ".env").exists()


def test_dotenv_refusal_to_stdout_prints_nothing(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set_many("a", {"A": "fine", "B": "${X}"})

    result = cli_json.invoke("export", "a")

    assert_exit(result, 1)
    assert result.stdout == ""


def test_a_refused_dotenv_value_exports_as_json(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "V", "${HOME}")

    result = cli_json.invoke("export", "a", "-t", "json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {"V": "${HOME}"}


# --- encrypted stores -----------------------------------------------------------------------------


def test_encrypted_stores_with_keys(cli: CliHarness) -> None:
    key = cli.key_file()
    library = cli.store()
    library.create_store("plain")
    library.set("plain", "A", "1")
    library.create_store("secret", encrypt=True, key=key)
    library.set("secret", "B", "2", key=key)

    result = cli.invoke("export", "plain", "secret", "-k", f"secret={key}")

    assert_exit(result, 0)
    assert result.stdout == "A=1\nB=2\n"


def test_encrypted_store_is_prompted_for_on_a_terminal(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=Passphrase(text="pw"))
    library.set("secret", "B", "2", key=Passphrase(text="pw"))
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke("export", "secret", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert result.stdout == "B=2\n"
    assert [kind for kind, _ in prompter.prompts] == ["secret"]


def test_encrypted_store_without_key_off_a_terminal_exits_4(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=Passphrase(text="pw"))

    result = cli_json.invoke("export", "secret", "-f", ".env")

    assert_exit(result, 4)
    assert not (cli_json.root / ".env").exists()


def test_wrong_key_exits_4(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=cli_json.key_file())

    result = cli_json.invoke("export", "secret", "-k", str(cli_json.key_file("other.key")))

    assert_exit(result, 4)


def test_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("export", "nope")

    assert_exit(result, 2)
    assert "nope" in result.stderr
