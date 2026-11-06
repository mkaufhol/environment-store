"""Global options, settings per command, the project file (D17, D29, D33, PD 10, PD 17)."""

import pytest
import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.output import out
from environment_store.cli.state import get_state
from environment_store.config.settings import ENV_CONNECTION, ENV_ORDERED_OVERWRITE
from tests.support.cli import CliHarness, assert_exit

_BROKEN: str = "stores = 'not a list'"
_PASSWORD_URL: str = "postgresql://user:hunter2@db.example/envs"  # noqa: S105 - test data


def _test_app() -> typer.Typer:
    app = build_app()

    @app.command("where", cls=EnvsCommand)
    def where(ctx: typer.Context) -> None:
        """Print the connection that wins."""
        out(get_state(ctx).settings().require_connection())

    @app.command("opens", cls=EnvsCommand)
    def opens(ctx: typer.Context) -> None:
        """Open the store, like every store command."""
        get_state(ctx).open_store(ctx).list_stores()
        out("opened")

    @app.command("offline", cls=EnvsCommand)
    def offline() -> None:
        """Open no store, like keygen (PD 17)."""
        out("ok")

    @app.command("flags", cls=EnvsCommand)
    def flags(ctx: typer.Context) -> None:
        """Show the global flags."""
        state = get_state(ctx)
        out(f"project={state.use_project} noinput={state.noinput}")

    @app.command("order", cls=EnvsCommand)
    def order(ctx: typer.Context) -> None:
        """Show the merge order setting."""
        out(str(get_state(ctx).settings().ordered_overwrite))

    return app


@pytest.fixture
def app() -> typer.Typer:
    return _test_app()


# --- connection precedence ---------------------------------------------------------------------


def test_connection_option_beats_environment_and_project_file(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    cli_json.project_file("connection = 'json:///from/file'")

    result = cli_json.invoke(
        "-c",
        "json:///from/option",
        "where",
        app=app,
        connection=False,
        env={ENV_CONNECTION: "json:///from/env"},
    )

    assert_exit(result, 0)
    assert result.stdout == "json:///from/option\n"


def test_long_connection_option_is_accepted(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("--connection", "json:///x", "where", app=app, connection=False)

    assert result.stdout == "json:///x\n"


def test_environment_beats_project_file(cli_json: CliHarness, app: typer.Typer) -> None:
    cli_json.project_file("connection = 'json:///from/file'")

    result = cli_json.invoke(
        "where", app=app, connection=False, env={ENV_CONNECTION: "json:///from/env"}
    )

    assert result.stdout == "json:///from/env\n"


def test_project_file_connection_is_used_last(cli_json: CliHarness, app: typer.Typer) -> None:
    cli_json.project_file("connection = 'json:///from/file'")

    result = cli_json.invoke("where", app=app, connection=False)

    assert result.stdout == "json:///from/file\n"


def test_project_file_is_found_from_a_subdirectory(
    cli_json: CliHarness, app: typer.Typer, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_json.project_file("connection = 'json://stores'")
    sub = cli_json.root / "deep" / "er"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    result = cli_json.invoke("where", app=app, connection=False)

    # Relative paths in the project file are anchored at its directory (PD 7).
    assert result.stdout == f"json://{cli_json.root / 'stores'}\n"


def test_no_project_ignores_the_project_file(cli_json: CliHarness, app: typer.Typer) -> None:
    cli_json.project_file("connection = 'json:///from/file'")

    result = cli_json.invoke("--no-project", "where", app=app, connection=False)

    assert_exit(result, 1)
    assert "no connection configured" in result.stderr


def test_global_flags_reach_the_command_state(cli_json: CliHarness, app: typer.Typer) -> None:
    assert cli_json.invoke("flags", app=app).stdout == "project=True noinput=False\n"
    assert (
        cli_json.invoke("--no-project", "--noinput", "flags", app=app).stdout
        == "project=False noinput=True\n"
    )


def test_empty_connection_option_is_refused(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("-c", "", "offline", app=app, connection=False)

    assert_exit(result, 1)
    assert "must not be empty" in result.stderr


# --- no connection (D29, PD 17) ----------------------------------------------------------------


def test_command_that_opens_a_store_without_connection_names_the_three_ways(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("opens", app=app, connection=False)

    assert_exit(result, 1)
    for way in ["-c/--connection", ENV_CONNECTION, "connection", ".envstore.toml"]:
        assert way in result.stderr
    assert result.stdout == ""


def test_command_that_opens_no_store_needs_no_connection(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("offline", app=app, connection=False)

    assert_exit(result, 0)
    assert result.stdout == "ok\n"


# --- configuration is validated for every command (PD 10) ----------------------------------------


@pytest.mark.parametrize("command", ["opens", "offline"])
def test_broken_project_file_fails_every_command(
    cli_json: CliHarness, app: typer.Typer, command: str
) -> None:
    cli_json.project_file(_BROKEN)

    result = cli_json.invoke(command, app=app)

    assert_exit(result, 1)
    assert ".envstore.toml" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("args", [["--help"], ["offline", "--help"], ["opens", "--help"]])
def test_help_works_with_a_broken_project_file_and_prints_no_warning(
    cli_json: CliHarness, app: typer.Typer, args: list[str]
) -> None:
    cli_json.project_file(_BROKEN)

    result = cli_json.invoke(*args, app=app)

    assert_exit(result, 0)
    assert "Usage:" in result.stdout
    assert result.stderr == ""


def test_bad_ordered_overwrite_variable_fails_every_command(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("offline", app=app, env={ENV_ORDERED_OVERWRITE: "maybe"})

    assert_exit(result, 1)
    assert ENV_ORDERED_OVERWRITE in result.stderr


@pytest.mark.parametrize(("value", "expected"), [("false", "False"), ("YES", "True"), ("", "True")])
def test_ordered_overwrite_variable_is_resolved(
    cli_json: CliHarness, app: typer.Typer, value: str, expected: str
) -> None:
    result = cli_json.invoke("order", app=app, env={ENV_ORDERED_OVERWRITE: value})

    assert result.stdout == f"{expected}\n"


# --- warnings -------------------------------------------------------------------------------------


def test_password_in_project_file_warns_once_per_command_even_when_overridden(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    cli_json.project_file(f"connection = '{_PASSWORD_URL}'")

    result = cli_json.invoke("opens", app=app)

    assert_exit(result, 0)
    assert result.stderr.count("Warning:") == 1
    assert ENV_CONNECTION in result.stderr
    assert "hunter2" not in result.stderr
    assert result.stdout == "opened\n"


def test_no_project_suppresses_the_password_warning(cli_json: CliHarness, app: typer.Typer) -> None:
    cli_json.project_file(f"connection = '{_PASSWORD_URL}'")

    result = cli_json.invoke("--no-project", "offline", app=app)

    assert result.stderr == ""


def test_untrusted_project_file_is_ignored_with_a_warning(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path = cli_json.project_file("connection = 'json:///from/file'")
    path.chmod(0o666)

    result = cli_json.invoke("where", app=app, connection=False)

    assert_exit(result, 1)
    assert f"Warning: ignoring project file '{path}'" in result.stderr
    assert "no connection configured" in result.stderr


def test_settings_are_resolved_once_per_command(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("twice", cls=EnvsCommand)
    def twice(ctx: typer.Context) -> None:
        state = get_state(ctx)
        assert state.settings() is state.settings()

    cli_json.project_file(f"connection = '{_PASSWORD_URL}'")

    result = cli_json.invoke("twice", app=app)

    assert_exit(result, 0)
    assert result.stderr.count("Warning:") == 1
