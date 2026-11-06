"""The root app: usage errors, exit codes, `--version`, interrupts (D24, PD 16, PD 21)."""

from importlib.metadata import version
from typing import Annotated

import pytest
import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.options import TypeOpt
from environment_store.cli.state import get_state
from environment_store.core.errors import (
    DecryptionError,
    EnvironmentStoreError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.formats.infer import Format
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _test_app() -> typer.Typer:
    app = build_app()

    @app.command("fail", cls=EnvsCommand)
    def fail(kind: str) -> None:
        errors: dict[str, EnvironmentStoreError] = {
            "validation": ValidationError("bad input"),
            "missing": StoreNotFoundError("store 'x' not found"),
            "exists": StoreExistsError("store 'x' already exists"),
            "key": DecryptionError("wrong key"),
        }
        raise errors[kind]

    @app.command("boom", cls=EnvsCommand)
    def boom() -> None:
        message = "an unexpected bug"
        raise RuntimeError(message)

    @app.command("ask", cls=EnvsCommand)
    def ask(ctx: typer.Context) -> None:
        state = get_state(ctx)
        state.prompter().secret("Key: ")

    @app.command("typed", cls=EnvsCommand)
    def typed(*, fmt: TypeOpt = None, count: Annotated[int, typer.Option()] = 0) -> None:
        typer.echo(f"{fmt} {count}")

    return app


@pytest.fixture
def app() -> typer.Typer:
    return _test_app()


# --- usage errors (exit 1, not click's 2) ----------------------------------------------------


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["no-such-command"], "No such command"),
        (["--no-such-option"], "No such option"),
        (["fail"], "Missing argument"),
        (["fail", "validation", "extra"], "unexpected extra argument"),
        (["typed", "-t", "yaml"], "Invalid value"),
        (["typed", "--count", "many"], "Invalid value"),
        (["-c"], "requires an argument"),
    ],
)
def test_usage_errors_exit_with_one_and_report_on_stderr(
    cli_json: CliHarness, app: typer.Typer, args: list[str], message: str
) -> None:
    result = cli_json.invoke(*args, app=app, connection=False)

    assert_exit(result, 1)
    assert message in result.stderr
    assert result.stdout == ""


def test_missing_command_after_global_options_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke()

    assert_exit(result, 1)
    assert "Missing command" in result.stderr


def test_no_arguments_show_the_help_and_exit_with_one(cli_json: CliHarness) -> None:
    result = cli_json.invoke(connection=False)

    # The plan's one exception to "nothing on stdout" for usage errors: the help goes to stdout.
    assert_exit(result, 1)
    assert "Usage:" in result.stdout
    assert "--connection" in result.stdout
    assert result.stderr == ""


def test_help_is_printed_on_stdout_with_exit_zero(cli_json: CliHarness) -> None:
    result = cli_json.invoke("--help", connection=False)

    assert_exit(result, 0)
    for option in ["--connection", "--no-project", "--noinput", "--version", "migrate"]:
        assert option in result.stdout


def test_help_keeps_square_brackets_literally(cli_json: CliHarness) -> None:
    # rich markup would eat "[keys]" (rich_markup_mode=None).
    result = cli_json.invoke("--help", connection=False)

    assert "[keys]" in result.stdout


def test_type_option_accepts_the_format_names(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("typed", "-t", "toml", app=app)

    assert_exit(result, 0)
    assert result.stdout == f"{Format.TOML} 0\n"


# --- library errors ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "code", "message"),
    [
        ("validation", 1, "bad input"),
        ("missing", 2, "store 'x' not found"),
        ("exists", 3, "store 'x' already exists"),
        ("key", 4, "wrong key"),
    ],
)
def test_library_errors_exit_with_their_category_code_without_traceback(
    cli_json: CliHarness, app: typer.Typer, kind: str, code: int, message: str
) -> None:
    result = cli_json.invoke("fail", kind, app=app)

    assert_exit(result, code)
    assert result.stderr == f"Error: {message}\n"
    assert result.stdout == ""
    assert isinstance(result.exception, SystemExit)


def test_success_exits_with_zero(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("typed", app=app)

    assert_exit(result, 0)


def test_concurrent_modification_exits_with_five(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("touch", cls=EnvsCommand)
    def touch(ctx: typer.Context) -> None:
        get_state(ctx).open_store(ctx).set("a", "X", "1")

    cli_json.store().create_store("a")
    opener = cli_json.hooked_opener(
        before={"write_store": lambda: cli_json.store().set("a", "RACE", "1")}
    )

    result = cli_json.invoke("touch", app=app, opener=opener)

    assert_exit(result, 5)
    assert "changed concurrently" in result.stderr
    assert cli_json.store().variables("a") == {"RACE": "1"}


def test_unexpected_exceptions_keep_their_traceback(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("boom", app=app)

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert "Error:" not in result.stderr


# --- interrupts -------------------------------------------------------------------------------


def test_ctrl_c_at_a_prompt_exits_with_130(cli_json: CliHarness, app: typer.Typer) -> None:
    prompter = RecordingPrompter(KeyboardInterrupt())

    result = cli_json.invoke("ask", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 130)
    assert result.stdout == ""


def test_end_of_input_at_a_prompt_exits_with_one(cli_json: CliHarness, app: typer.Typer) -> None:
    prompter = RecordingPrompter(EOFError())

    result = cli_json.invoke("ask", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 1)
    assert "Aborted" in result.stderr
    assert result.stdout == ""


# --- --version (PD 16) ---------------------------------------------------------------------------


def test_version_prints_the_installed_version_without_a_connection(cli_json: CliHarness) -> None:
    result = cli_json.invoke("--version", connection=False)

    assert_exit(result, 0)
    assert result.stdout == f"environment-store {version('environment-store')}\n"
    assert result.stderr == ""


def test_version_ignores_a_broken_project_file(cli_json: CliHarness) -> None:
    cli_json.project_file("this is not toml")

    result = cli_json.invoke("--version", connection=False)

    assert_exit(result, 0)
    assert result.stderr == ""
