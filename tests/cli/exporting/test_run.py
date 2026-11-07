"""`envs run`: the merged environment, `--`, process replacement and exit codes (§6.13, PD 28)."""

import dataclasses
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NoReturn, override

import pytest
from typer.testing import CliRunner

from environment_store.cli.app import app as envs
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.secrets import Passphrase
from environment_store.library.store import EnvironmentStore, open_configured_adapter
from tests.support.cli import (
    CliHarness,
    Executed,
    HookedAdapter,
    RecordingPrompter,
    assert_exit,
)

_PRESET: Final = "ENVS_TEST_PRESET"


def _arrange(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"DB_HOST": "localhost", "PORT": "5432", _PRESET: "store"})
    library.create_store("customer-a")
    library.set("customer-a", "DB_HOST", "10.0.0.5")


def _executed(cli: CliHarness) -> tuple[str, list[str], dict[str, str]]:
    assert len(cli.exec_calls) == 1
    return cli.exec_calls[0]


# --- in-process: the fake exec_process records the call -------------------------------------------


def test_run_replaces_the_process_with_the_command_and_merged_environment(
    cli: CliHarness,
) -> None:
    _arrange(cli)

    result = cli.invoke("run", "base", "customer-a", "--", "app", "--port", "1")

    assert isinstance(result.exception, Executed)
    file, argv, env = _executed(cli)
    assert file == "app"
    assert argv == ["app", "--port", "1"]
    assert env["DB_HOST"] == "10.0.0.5"
    assert env["PORT"] == "5432"


def test_arguments_after_the_separator_are_untouched(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "-o", "base", "--", "cmd", "-o", "--", "--help", "-k", "x")

    _, argv, _ = _executed(cli_json)
    assert argv == ["cmd", "-o", "--", "--help", "-k", "x"]


def test_the_current_environment_is_kept(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "base", "--", "cmd", env={"ENVS_TEST_OTHER": "kept"})

    _, _, env = _executed(cli_json)
    assert env["ENVS_TEST_OTHER"] == "kept"


def test_preset_variables_win_without_overwrite(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "base", "--", "cmd", env={_PRESET: "preset"})

    _, _, env = _executed(cli_json)
    assert env[_PRESET] == "preset"


def test_overwrite_lets_store_values_win(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "-o", "base", "--", "cmd", env={_PRESET: "preset"})

    _, _, env = _executed(cli_json)
    assert env[_PRESET] == "store"


def test_first_wins(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "--first-wins", "base", "customer-a", "--", "cmd")

    _, _, env = _executed(cli_json)
    assert env["DB_HOST"] == "localhost"


def test_nested_prefixes_variables_instead_of_merging(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    cli_json.invoke("run", "--nested", "base", "customer-a", "--", "cmd")

    _, _, env = _executed(cli_json)
    assert env["BASE__DB_HOST"] == "localhost"
    assert env["CUSTOMER_A__DB_HOST"] == "10.0.0.5"
    assert "DB_HOST" not in env


def test_project_store_list_is_the_default(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file('stores = ["customer-a"]\n')

    cli_json.invoke("run", "--", "cmd")

    _, _, env = _executed(cli_json)
    assert env["DB_HOST"] == "10.0.0.5"
    assert "PORT" not in env


def test_encrypted_store_with_a_key(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=key)
    library.set("secret", "API_URL", "value", key=key)

    cli_json.invoke("run", "secret", "-k", f"secret={key}", "--", "cmd")

    _, _, env = _executed(cli_json)
    assert env["API_URL"] == "value"


def test_encrypted_store_without_a_key_exits_4_and_runs_nothing(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=Passphrase(text="pw"))

    result = cli_json.invoke("run", "secret", "--", "cmd")

    assert_exit(result, 4)
    assert cli_json.exec_calls == []


@pytest.mark.parametrize(
    "args", [["base"], ["base", "--"], ["base", "--", ""], ["base", "--", "", "x"]]
)
def test_a_missing_command_exits_1_before_any_prompt(cli_json: CliHarness, args: list[str]) -> None:
    library = cli_json.store()
    library.create_store("base", encrypt=True, key=Passphrase(text="pw"))
    prompter = RecordingPrompter()

    result = cli_json.invoke("run", *args, stdin_tty=True, prompter=prompter)

    assert_exit(result, 1)
    assert "--" in result.stderr
    assert "Traceback" not in result.stderr
    assert prompter.prompts == []
    assert cli_json.exec_calls == []


def test_a_command_the_os_rejects_as_invalid_exits_1_without_a_traceback(
    cli_json: CliHarness,
) -> None:
    _arrange(cli_json)
    cli_json.exec_error = ValueError("embedded null byte")

    result = cli_json.invoke("run", "base", "--", "nope", "x")

    assert_exit(result, 1)
    assert "nope" in result.stderr
    assert "embedded null byte" in result.stderr
    assert "Traceback" not in result.stderr


def test_unknown_option_before_the_separator_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke("run", "--bogus", "--", "cmd")

    assert_exit(result, 1)
    assert cli_json.exec_calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (FileNotFoundError(2, "No such file or directory"), 127),
        (PermissionError(13, "Permission denied"), 126),
        (OSError(8, "Exec format error"), 126),
    ],
)
def test_a_command_that_cannot_be_started_maps_to_the_shell_codes(
    cli_json: CliHarness, error: OSError, code: int
) -> None:
    _arrange(cli_json)
    cli_json.exec_error = error

    result = cli_json.invoke("run", "base", "--", "nope", "x")

    assert_exit(result, code)
    assert "nope" in result.stderr
    assert str(error.strerror) in result.stderr
    assert "Traceback" not in result.stderr


def test_the_store_is_closed_before_the_process_is_replaced(cli: CliHarness) -> None:
    _arrange(cli)
    events: list[str] = []

    class _Recording(HookedAdapter):
        @override
        def close(self) -> None:
            events.append("close")
            super().close()

    def opener(connection: str, setup: SetupMode) -> Adapter:
        return _Recording(open_configured_adapter(connection, setup), before={}, after={})

    def exec_process(file: str, argv: list[str], env: Mapping[str, str]) -> NoReturn:
        events.append("exec")
        raise Executed(file, argv, dict(env))

    runtime = dataclasses.replace(cli.runtime(opener=opener), exec_process=exec_process)

    result = CliRunner().invoke(
        envs, ["-c", cli.connection, "run", "base", "--", "cmd"], obj=runtime
    )

    assert isinstance(result.exception, Executed)
    assert events[:2] == ["close", "exec"]


# --- end to end: a real interpreter, a real exec --------------------------------------------------


@pytest.fixture
def backend(tmp_path: Path) -> dict[str, str]:
    connection = f"json://{tmp_path / 'stores'}"
    with EnvironmentStore(connection) as library:
        library.create_store("a")
        library.set_many("a", {"ENVS_E2E": "from-store", _PRESET: "store"})
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("ENV_STORE_")
    }
    environment["ENV_STORE_CONNECTION"] = connection
    return environment


def _envs(*args: str) -> list[str]:
    return [sys.executable, "-m", "environment_store.cli", "--no-project", *args]


@pytest.mark.skipif(sys.platform == "win32", reason="exec() replaces the process on POSIX only")
def test_end_to_end_exit_code_is_passed_through(backend: dict[str, str], tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        _envs("run", "a", "--", sys.executable, "-c", "import sys; sys.exit(7)"),
        env=backend,
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 7


@pytest.mark.skipif(sys.platform == "win32", reason="exec() replaces the process on POSIX only")
def test_end_to_end_variables_reach_the_command(backend: dict[str, str], tmp_path: Path) -> None:
    code = "import os; print(os.environ['ENVS_E2E'], os.environ['ENVS_TEST_PRESET'])"
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        _envs("run", "a", "--", sys.executable, "-c", code),
        env={**backend, _PRESET: "preset"},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "from-store preset\n"


@pytest.mark.skipif(sys.platform == "win32", reason="exec() replaces the process on POSIX only")
def test_end_to_end_the_process_is_replaced(backend: dict[str, str], tmp_path: Path) -> None:
    with subprocess.Popen(  # noqa: S603 - fixed interpreter and arguments
        _envs("run", "a", "--", sys.executable, "-c", "import os; print(os.getpid())"),
        env=backend,
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        stdout, _ = process.communicate(timeout=60)

    assert process.returncode == 0
    assert int(stdout) == process.pid


@pytest.mark.skipif(sys.platform == "win32", reason="exec() replaces the process on POSIX only")
def test_end_to_end_missing_command_exits_127(backend: dict[str, str], tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        _envs("run", "a", "--", "envs-test-no-such-command"),
        env=backend,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 127
    assert "envs-test-no-such-command" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="exec() replaces the process on POSIX only")
def test_end_to_end_key_variables_never_reach_the_command(
    backend: dict[str, str], tmp_path: Path
) -> None:
    # D53: an encrypted store read with its key variable, plus a variable of an unused store.
    with EnvironmentStore(backend["ENV_STORE_CONNECTION"]) as library:
        library.create_store("locked", encrypt=True, key=Passphrase(text="pw"))
        library.set("locked", "ENVS_LOCKED", "opened", key=Passphrase(text="pw"))
    code = (
        "import os; print(os.environ['ENVS_LOCKED'], os.environ['ENVS_E2E'], "
        "sorted(n for n in os.environ if n.startswith('ENV_STORE_KEY')))"
    )
    env = {
        **backend,
        "ENV_STORE_KEY_LOCKED": "pw\n",
        "ENV_STORE_KEY_UNUSED": "x",
        "ENV_STORE_KEYRING": "kept",
    }

    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        _envs("run", "a", "locked", "--", sys.executable, "-c", code),
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "opened from-store ['ENV_STORE_KEYRING']\n"
