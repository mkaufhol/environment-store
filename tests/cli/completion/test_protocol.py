"""Shell completion through the protocol the scripts use (spec §6.15, D54)."""

import hashlib
import sys
from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from environment_store.cli.app import app as envs
from environment_store.config.settings import ENV_CONNECTION
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.errors import BackendError, MissingExtraError
from environment_store.library.store import open_configured_adapter
from tests.cli.completion.protocol import Item, Shell, complete, parse
from tests.support.cli import CliHarness, RecordingPrompter, cli_harness

_SHELLS: Final[tuple[Shell, ...]] = ("bash", "zsh", "fish")
_COMMANDS: Final = {
    "completion",
    "cp-store",
    "create-store",
    "encrypt",
    "export",
    "export-shell",
    "get",
    "import",
    "keygen",
    "ls",
    "ls-store",
    "migrate",
    "mv-store",
    "rekey",
    "rm",
    "rm-store",
    "run",
    "set",
    "tui",
}


def _values(cli: CliHarness, *args: str, incomplete: str = "", shell: Shell = "bash") -> list[str]:
    items = parse(complete(cli, *args, incomplete=incomplete, shell=shell), shell)
    assert all(item.type == "plain" for item in items), items
    return [item.value for item in items]


def _stores(cli: CliHarness, *names: str, encrypted: tuple[str, ...] = ()) -> None:
    store = cli.store()
    for name in names:
        store.create_store(name)
    for name in encrypted:
        store.create_store(name, encrypt=True, key=cli.key_file(f"{name}.key"))


# --- commands, options, choices --------------------------------------------------------------


@pytest.mark.parametrize("shell", _SHELLS)
def test_command_names_complete_in_every_shell(cli_json: CliHarness, shell: Shell) -> None:
    assert set(_values(cli_json, shell=shell)) == _COMMANDS


def test_a_command_prefix_completes_the_matching_commands(cli_json: CliHarness) -> None:
    assert sorted(_values(cli_json, incomplete="ls")) == ["ls", "ls-store"]


def test_options_of_a_command_complete(cli_json: CliHarness) -> None:
    assert _values(cli_json, "ls", incomplete="--v") == ["--values"]


def test_global_options_complete_before_the_command(cli_json: CliHarness) -> None:
    assert "--no-project" in _values(cli_json, incomplete="--no")


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("export", "-t"), ["dotenv", "json", "toml"]),
        (("import", "-s", "a", "--type"), ["dotenv", "json", "toml"]),
        (("completion",), ["bash", "zsh", "fish"]),
    ],
)
def test_option_values_with_a_fixed_set_complete(
    cli_json: CliHarness, args: tuple[str, ...], expected: list[str]
) -> None:
    assert _values(cli_json, *args) == expected


# --- stores ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("ls",),
        ("ls", "alpha"),
        ("get", "KEY"),
        ("export",),
        ("export-shell",),
        ("run",),
        ("set", "-s"),
        ("rm", "--store"),
        ("import", "-s"),
        ("rekey", "-s"),
        ("encrypt", "-s"),
        ("rm-store",),
        ("cp-store",),
        ("mv-store",),
    ],
)
def test_existing_store_names_complete_where_an_existing_store_is_expected(
    cli: CliHarness, args: tuple[str, ...]
) -> None:
    _stores(cli, "alpha", "beta", encrypted=("vault",))

    assert _values(cli, *args) == ["alpha", "beta", "vault"]


def test_store_names_complete_by_prefix(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha", "beta", "base")

    assert _values(cli_json, "ls", incomplete="b") == ["base", "beta"]


@pytest.mark.parametrize(
    "args",
    [("create-store",), ("cp-store", "alpha"), ("mv-store", "alpha")],
)
def test_new_store_names_never_complete(cli_json: CliHarness, args: tuple[str, ...]) -> None:
    _stores(cli_json, "alpha", "beta")

    assert _values(cli_json, *args) == []


@pytest.mark.parametrize("command", ["ls", "get", "export", "export-shell", "run"])
def test_the_store_part_of_a_reading_key_completes(cli_json: CliHarness, command: str) -> None:
    _stores(cli_json, "alpha", "beta")
    args = (command, "KEY", "-k") if command == "get" else (command, "-k")

    assert _values(cli_json, *args) == ["alpha=", "beta="]
    assert _values(cli_json, *args, incomplete="b") == ["beta="]


def test_the_path_part_of_a_reading_key_is_left_to_the_shell(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha")

    items = parse(complete(cli_json, "ls", "-k", incomplete="alpha=ke"))

    assert items == [Item("file", "ke")]


@pytest.mark.parametrize(
    ("words", "cword", "expected"),
    [
        # bash splits at '=' (COMP_WORDBREAKS): `-k alpha=ke` and `-k alpha=`.
        ("envs ls -k alpha = ke", "5", [Item("file", "ke")]),
        ("envs ls -k alpha =", "4", [Item("file", "")]),
        ("envs ls --key = al", "4", [Item("plain", "alpha=")]),
    ],
)
def test_bash_words_split_at_equals_signs_are_joined_again(
    cli_json: CliHarness, words: str, cword: str, expected: list[Item]
) -> None:
    _stores(cli_json, "alpha")
    env = {
        ENV_CONNECTION: cli_json.connection,
        "COMP_WORDS": words,
        "COMP_CWORD": cword,
    }

    result = complete(cli_json, connection=False, env=env)

    assert parse(result) == expected


# --- variables -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [("get",), ("rm", "-s", "alpha"), ("set", "-s", "alpha")],
)
def test_variable_names_of_a_plaintext_store_complete(
    cli: CliHarness, args: tuple[str, ...]
) -> None:
    _stores(cli, "alpha")
    cli.store().set_many("alpha", {"HOST": "h", "PORT": "1", "USER": "u"})
    cli.project_file("stores = ['alpha']")

    assert _values(cli, *args) == ["HOST", "PORT", "USER"]
    assert _values(cli, *args, incomplete="P") == ["PORT"]


def test_get_completes_the_names_of_every_plaintext_store_of_the_project_file(
    cli_json: CliHarness,
) -> None:
    _stores(cli_json, "alpha", "beta")
    cli_json.store().set("alpha", "HOST", "h")
    cli_json.store().set_many("beta", {"HOST": "x", "DEBUG": "1"})
    cli_json.project_file("stores = ['alpha', 'beta']")

    assert _values(cli_json, "get") == ["DEBUG", "HOST"]


@pytest.mark.parametrize("args", [("get",), ("rm", "-s", "vault"), ("set", "-s", "vault")])
def test_encrypted_stores_complete_no_variable_names_and_read_no_key(
    cli: CliHarness, args: tuple[str, ...]
) -> None:
    _stores(cli, encrypted=("vault",))
    key = cli.root / "vault.key"
    cli.store().set("vault", "SECRET", "s", key=key)
    cli.project_file(f"stores = ['vault']\n[keys]\nvault = '{key}'\n")
    env = {"ENV_STORE_KEY_VAULT": key.read_text(encoding="utf-8").strip()}
    runtime = cli.runtime(stdin_tty=True, prompter=RecordingPrompter())

    result = complete(cli, *args, env=env, runtime=runtime)

    assert parse(result) == []


def test_a_mix_completes_only_the_plaintext_variable_names(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha", encrypted=("vault",))
    cli_json.store().set("alpha", "HOST", "h")
    cli_json.store().set("vault", "SECRET", "s", key=cli_json.root / "vault.key")
    cli_json.project_file("stores = ['alpha', 'vault']")

    assert _values(cli_json, "get") == ["HOST"]


def test_a_missing_store_completes_no_variable_names(cli_json: CliHarness) -> None:
    assert _values(cli_json, "rm", "-s", "nope") == []


# --- paths -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("keygen",),
        ("import", "-s", "a", "-f"),
        ("export", "--file"),
        ("set", "-s", "a", "-k"),
        ("create-store", "x", "-e", "-k"),
        ("create-store", "x", "-e", "--generate-key"),
        ("cp-store", "a", "b", "--new-key"),
        ("rekey", "-s", "a", "--new-key"),
        ("encrypt", "-s", "a", "--generate-key"),
    ],
)
@pytest.mark.parametrize("shell", _SHELLS)
def test_paths_are_left_to_the_shell_file_completion(
    cli_json: CliHarness, args: tuple[str, ...], shell: Shell
) -> None:
    items = parse(complete(cli_json, *args, incomplete="ke", shell=shell), shell)

    assert items == [Item("file", "ke")]


# --- the backend -----------------------------------------------------------------------------


def test_the_connection_comes_from_the_environment(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha")

    result = complete(cli_json, "ls", connection=False, env={ENV_CONNECTION: cli_json.connection})

    assert parse(result) == [Item("plain", "alpha")]


def test_the_connection_comes_from_the_project_file(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha")
    cli_json.project_file(f"connection = '{cli_json.connection}'")

    assert parse(complete(cli_json, "ls", connection=False)) == [Item("plain", "alpha")]


def test_c_on_the_line_wins_over_the_environment(cli_json: CliHarness, tmp_path: Path) -> None:
    _stores(cli_json, "alpha")
    with cli_harness(tmp_path / "other", "json") as other:
        other.store().create_store("other")
        env = {ENV_CONNECTION: other.connection}

        assert parse(complete(cli_json, "ls", env=env)) == [Item("plain", "alpha")]


def test_no_project_on_the_line_ignores_the_project_file(cli_json: CliHarness) -> None:
    _stores(cli_json, "alpha")
    cli_json.project_file(f"connection = '{cli_json.connection}'")

    assert parse(complete(cli_json, "--no-project", "ls", connection=False)) == []


def test_completion_opens_the_backend_read_only(cli_json: CliHarness) -> None:
    modes: list[SetupMode] = []

    def opener(connection: str, setup: SetupMode) -> Adapter:
        modes.append(setup)
        return open_configured_adapter(connection, setup)

    complete(cli_json, "ls", runtime=cli_json.runtime(opener=opener))

    assert modes == [SetupMode.READ_ONLY]


# --- read-only and silent --------------------------------------------------------------------


def test_an_empty_sqlite_file_stays_byte_identical(cli_json: CliHarness, tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    database.touch()
    env = {ENV_CONNECTION: f"sqlite:///{database}"}

    for args in [("ls",), ("get",), ("rm", "-s", "a")]:
        assert parse(complete(cli_json, *args, connection=False, env=env)) == []

    assert hashlib.sha256(database.read_bytes()).hexdigest() == hashlib.sha256(b"").hexdigest()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["empty.db"]


@pytest.mark.parametrize(
    "connection",
    ["json://{}/missing/stores", "toml://{}/missing/stores", "sqlite:///{}/missing/e.db"],
)
def test_a_missing_location_is_not_created(
    cli_json: CliHarness, tmp_path: Path, connection: str
) -> None:
    env = {ENV_CONNECTION: connection.format(tmp_path)}

    for args in [("ls",), ("rm-store",), ("rm", "-s", "a")]:
        assert parse(complete(cli_json, *args, connection=False, env=env)) == []

    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    ("project", "env"),
    [
        ("", {}),
        ("this is not toml", {}),
        ("unknown_key = 1", {}),
        ("", {ENV_CONNECTION: "nope://x"}),
        ("", {ENV_CONNECTION: "sqlite:///"}),
        ("", {"ENV_STORE_ORDERED_OVERWRITE": "maybe"}),
    ],
)
@pytest.mark.parametrize("shell", _SHELLS)
def test_a_broken_configuration_completes_nothing_silently(
    cli_json: CliHarness, project: str, env: dict[str, str], shell: Shell
) -> None:
    if project:
        cli_json.project_file(project)

    result = complete(cli_json, "ls", connection=False, env=env, shell=shell)

    assert parse(result, shell) == []


@pytest.mark.parametrize(
    "error",
    [MissingExtraError("postgres"), BackendError("unreachable"), RuntimeError("bug")],
)
def test_a_failing_backend_completes_nothing_silently(
    cli_json: CliHarness, error: Exception
) -> None:
    def opener(connection: str, setup: SetupMode) -> Adapter:
        raise error

    runtime = cli_json.runtime(opener=opener)

    assert parse(complete(cli_json, "ls", runtime=runtime)) == []
    assert parse(complete(cli_json, "get", runtime=runtime)) == []


def test_a_credentials_warning_of_the_project_file_is_not_printed(cli_json: CliHarness) -> None:
    cli_json.project_file("connection = 'postgresql://u:secret@127.0.0.1:1/db'\nstores = ['a']")

    result = complete(cli_json, "get", connection=False)

    assert parse(result) == []
    assert "secret" not in result.stdout


def test_a_postgres_connection_without_the_extra_completes_nothing(
    cli_json: CliHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "psycopg", None)
    env = {ENV_CONNECTION: "postgresql://u@127.0.0.1:1/db"}

    assert parse(complete(cli_json, "ls", connection=False, env=env)) == []


def test_completing_after_an_unknown_command_is_silent(cli_json: CliHarness) -> None:
    # Like click: the line is parsed leniently, so the group offers its commands again.
    assert {item.value for item in parse(complete(cli_json, "no-such-command"))} == _COMMANDS


@pytest.mark.parametrize("instruction", ["bash_source", "tcsh_complete", "complete", "x"])
def test_an_unknown_instruction_answers_nothing(cli_json: CliHarness, instruction: str) -> None:
    result = complete(cli_json, env={"_ENVS_COMPLETE": instruction})

    assert (result.exit_code, result.stdout, result.stderr) == (0, "", "")


def test_the_protocol_variable_follows_the_program_name(cli_json: CliHarness) -> None:
    items = parse(complete(cli_json, prog_name="environment-store", incomplete="ls-"))

    assert items == [Item("plain", "ls-store")]


@pytest.mark.parametrize(
    "env",
    [
        {"_ENVS_COMPLETE": "bash_complete"},
        {"_ENVS_COMPLETE": "zsh_complete", "COMP_WORDS": "envs ls", "COMP_CWORD": "one"},
        {"_ENVS_COMPLETE": "fish_complete", "COMP_CWORD": ""},
    ],
)
def test_a_malformed_request_answers_nothing_silently(
    cli_json: CliHarness, env: dict[str, str]
) -> None:
    result = CliRunner().invoke(envs, [], env=env, prog_name="envs", obj=cli_json.runtime())

    assert (result.exit_code, result.stdout, result.stderr) == (0, "", "")
