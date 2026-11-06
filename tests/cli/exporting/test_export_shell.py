"""`envs export-shell`: POSIX statements for `eval` (spec §6.12, D23, D30)."""

import subprocess
from typing import Final

from hypothesis import HealthCheck, given, settings

from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, temporary_cli
from tests.support.strategies import values

_SHELL: Final = "/bin/sh"


def _sh(script: str, *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - fixed shell, script passed as an argument
        [_SHELL, "-c", script], capture_output=True, text=False, check=True, env=env or {}
    )
    return result.stdout.decode("utf-8")


def _arrange(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"DB_HOST": "localhost", "PORT": "5432"})
    library.create_store("customer-a")
    library.set("customer-a", "DB_HOST", "10.0.0.5")


def test_statements_keep_preset_variables_without_overwrite(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export-shell", "base", "customer-a")

    assert_exit(result, 0)
    assert result.stdout == (
        '[ -n "${DB_HOST+x}" ] || export DB_HOST=10.0.0.5\n[ -n "${PORT+x}" ] || export PORT=5432\n'
    )
    script = 'eval "$1"; printf "%s %s" "$DB_HOST" "$PORT"'
    output = _sh(f"set -- {_quote(result.stdout)}; {script}", env={"DB_HOST": "preset"})
    assert output == "preset 5432"


def test_overwrite_replaces_preset_variables(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export-shell", "-o", "base", "customer-a")

    assert_exit(result, 0)
    assert result.stdout == "export DB_HOST=10.0.0.5\nexport PORT=5432\n"
    output = _sh(
        f'set -- {_quote(result.stdout)}; eval "$1"; printf "%s" "$DB_HOST"',
        env={"DB_HOST": "preset"},
    )
    assert output == "10.0.0.5"


def test_output_is_safe_under_set_e_when_the_last_variable_is_preset(
    cli_json: CliHarness,
) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export-shell", "base")

    assert_exit(result, 0)
    output = _sh(
        f'set -e; set -- {_quote(result.stdout)}; eval "$1"; printf done',
        env={"PORT": "1"},
    )
    assert output == "done"


def test_first_wins(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export-shell", "-o", "--first-wins", "base", "customer-a")

    assert_exit(result, 0)
    assert "export DB_HOST=localhost\n" in result.stdout


def test_nested_prefixes_variables_with_the_store_name(cli: CliHarness) -> None:
    _arrange(cli)

    result = cli.invoke("export-shell", "-o", "--nested", "base", "customer-a")

    assert_exit(result, 0)
    assert result.stdout == (
        "export BASE__DB_HOST=localhost\n"
        "export BASE__PORT=5432\n"
        "export CUSTOMER_A__DB_HOST=10.0.0.5\n"
    )


def test_encrypted_store_is_prompted_for_on_stderr_only(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=Passphrase(text="pw"))
    library.set("secret", "TOKEN", "t", key=Passphrase(text="pw"))
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke("export-shell", "-o", "secret", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert result.stdout == "export TOKEN=t\n"


def test_encrypted_store_with_a_key_file(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=key)
    library.set("secret", "TOKEN", "t", key=key)

    result = cli_json.invoke("export-shell", "-o", "secret", "-k", str(key))

    assert_exit(result, 0)
    assert result.stdout == "export TOKEN=t\n"


def test_missing_key_exits_4(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("secret", encrypt=True, key=cli_json.key_file())

    result = cli_json.invoke("export-shell", "secret")

    assert_exit(result, 4)
    assert result.stdout == ""


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(value=values())
def test_evaluated_output_reproduces_every_value_exactly(value: str) -> None:
    with temporary_cli() as cli:
        library = cli.store()
        library.create_store("a")
        library.set("a", "V", value)

        result = cli.invoke("export-shell", "a")

        assert_exit(result, 0)
        # The bytes, not result.stdout: CliRunner normalises CRLF in the text form.
        statements = result.stdout_bytes.decode("utf-8")
        script = f'set -- {_quote(statements)}; eval "$1"; printf "%s" "$V"'
        assert _sh(script) == value


def _quote(text: str) -> str:
    # The statements are passed as $1, so the test's own quoting cannot hide a quoting bug.
    return "'" + text.replace("'", "'\"'\"'") + "'"
