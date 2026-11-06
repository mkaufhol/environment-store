"""`require_confirmation`: `-y`, a terminal question, or a refusal (spec §6, D33, D35)."""

import pytest
import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.confirm import require_confirmation
from environment_store.cli.options import YesOpt
from environment_store.cli.output import out
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


@pytest.fixture
def app() -> typer.Typer:
    app = build_app()

    @app.command("destroy", cls=EnvsCommand)
    def destroy(ctx: typer.Context, *, yes: YesOpt = False) -> None:
        require_confirmation(ctx, "Delete store 'a'?", yes=yes)
        out("destroyed")

    return app


@pytest.mark.parametrize("flag", ["-y", "--yes"])
@pytest.mark.parametrize("stdin_tty", [True, False])
def test_yes_proceeds_without_asking(
    cli_json: CliHarness, app: typer.Typer, flag: str, *, stdin_tty: bool
) -> None:
    result = cli_json.invoke("destroy", flag, app=app, stdin_tty=stdin_tty)

    assert_exit(result, 0)
    assert result.stdout == "destroyed\n"


def test_terminal_answer_yes_proceeds(cli_json: CliHarness, app: typer.Typer) -> None:
    prompter = RecordingPrompter("y")

    result = cli_json.invoke("destroy", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert prompter.prompts == [("confirm", "Delete store 'a'?")]


def test_terminal_answer_no_exits_with_one_and_does_nothing(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("destroy", app=app, stdin_tty=True, prompter=RecordingPrompter("n"))

    assert_exit(result, 1)
    assert result.stdout == ""
    assert "Aborted" in result.stderr


def test_without_a_terminal_confirmation_is_refused_naming_yes(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("destroy", app=app)

    assert_exit(result, 1)
    assert "-y/--yes" in result.stderr
    assert result.stdout == ""


def test_noinput_on_a_terminal_refuses_instead_of_asking(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("--noinput", "destroy", app=app, stdin_tty=True)

    assert_exit(result, 1)
    assert "-y/--yes" in result.stderr
