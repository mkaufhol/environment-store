"""`CliState`: stdin consumption, secret input, interaction and store lifetime."""

from dataclasses import replace

import pytest
import typer
from typer.core import TyperCommand
from typer.testing import CliRunner

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.output import out
from environment_store.cli.state import get_state
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.library.store import EnvironmentStore, open_configured_adapter
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


def _test_app() -> typer.Typer:
    app = build_app()

    @app.command("echo-stdin", cls=EnvsCommand)
    def echo_stdin(ctx: typer.Context) -> None:
        state = get_state(ctx)
        state.claim_stdin("the value")
        out(state.read_stdin(), newline=False)

    @app.command("claim-twice", cls=EnvsCommand)
    def claim_twice(ctx: typer.Context) -> None:
        state = get_state(ctx)
        state.claim_stdin("-k -")
        state.claim_stdin("the value")

    @app.command("secret-input", cls=EnvsCommand)
    def secret_input(ctx: typer.Context) -> None:
        state = get_state(ctx)
        given = state.secret_input("-k -")
        out(f"tty={given.stdin_is_tty} prompter={given.prompter is not None}")
        out(given.read_stdin().decode())
        state.claim_stdin("the value")

    @app.command("interactive", cls=EnvsCommand)
    def interactive(ctx: typer.Context) -> None:
        out(str(get_state(ctx).interactive()))

    @app.command("stores", cls=EnvsCommand)
    def stores(ctx: typer.Context) -> None:
        state = get_state(ctx)
        first = state.open_store(ctx)
        assert state.open_store(ctx) is first
        assert state.open_store(ctx, setup=SetupMode.NONE) is not first
        first.list_stores()

    return app


@pytest.fixture
def app() -> typer.Typer:
    return _test_app()


# --- stdin ---------------------------------------------------------------------------------------


def test_stdin_is_read_byte_exact_without_newline_translation(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("echo-stdin", app=app, input=b"a\r\nb\rc\n")

    assert_exit(result, 0)
    assert result.stdout_bytes == b"a\r\nb\rc\n"


def test_stdin_that_is_not_utf8_is_refused_with_exit_one(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("echo-stdin", app=app, input=b"\xff\xfe secret")

    assert_exit(result, 1)
    assert "not valid UTF-8" in result.stderr
    assert "secret" not in result.stderr


def test_stdin_can_be_claimed_once_per_command(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("claim-twice", app=app)

    assert_exit(result, 1)
    assert "-k -" in result.stderr
    assert "the value" in result.stderr


def test_secret_input_reads_stdin_through_a_claim(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("secret-input", app=app, input="pw\n")

    # Reading the secret claimed stdin, so the second claim fails.
    assert_exit(result, 1)
    assert result.stdout == "tty=False prompter=False\npw\n\n"
    assert "already used for -k -" in result.stderr


@pytest.mark.parametrize(
    ("stdin_tty", "noinput", "expected"),
    [(True, False, "True"), (True, True, "False"), (False, False, "False"), (False, True, "False")],
)
def test_prompts_are_allowed_only_on_a_terminal_without_noinput(
    cli_json: CliHarness, app: typer.Typer, *, stdin_tty: bool, noinput: bool, expected: str
) -> None:
    args = ["--noinput", "interactive"] if noinput else ["interactive"]

    result = cli_json.invoke(*args, app=app, stdin_tty=stdin_tty)

    assert result.stdout == f"{expected}\n"


def test_secret_input_on_a_terminal_carries_the_prompter(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("secret-input", app=app, stdin_tty=True, input="x")

    assert result.stdout.startswith("tty=True prompter=True\n")


def test_default_prompter_is_the_terminal_prompter(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("which", cls=EnvsCommand)
    def which(ctx: typer.Context) -> None:
        out(type(get_state(ctx).prompter()).__name__)

    runtime = replace(cli_json.runtime(), prompter=None)

    result = CliRunner().invoke(app, ["which"], obj=runtime)

    assert result.stdout == "TerminalPrompter\n"


def test_injected_prompter_is_used(cli_json: CliHarness) -> None:
    app = build_app()
    prompter = RecordingPrompter("answer")

    @app.command("ask", cls=EnvsCommand)
    def ask(ctx: typer.Context) -> None:
        out(get_state(ctx).prompter().secret("Q: "))

    result = cli_json.invoke("ask", app=app, prompter=prompter)

    assert result.stdout == "answer\n"
    assert prompter.prompts == [("secret", "Q: ")]


# --- stores --------------------------------------------------------------------------------------


def test_open_store_reuses_one_store_per_connection_and_closes_it_after_the_command(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    opened: list[tuple[SetupMode, Adapter]] = []

    def opener(url: str, setup: SetupMode) -> Adapter:
        adapter = open_configured_adapter(url, setup)
        opened.append((setup, adapter))
        return adapter

    result = cli_json.invoke("stores", app=app, opener=opener)

    assert_exit(result, 0)
    assert [setup for setup, _ in opened] == [SetupMode.AUTO, SetupMode.NONE]


def test_store_is_closed_even_when_the_command_fails(cli_json: CliHarness) -> None:
    app = build_app()
    seen: list[EnvironmentStore] = []

    @app.command("fails", cls=EnvsCommand)
    def fails(ctx: typer.Context) -> None:
        seen.append(get_state(ctx).open_store(ctx))
        seen[0].store_info("missing")

    result = cli_json.invoke("fails", app=app)

    assert_exit(result, 2)
    assert seen[0].closed


def test_open_store_with_another_connection_uses_it(cli_json: CliHarness) -> None:
    app = build_app()
    other = cli_json.root / "other"

    @app.command("other", cls=EnvsCommand)
    def other_store(ctx: typer.Context) -> None:
        get_state(ctx).open_store(ctx, connection=f"json://{other}").create_store("x")

    result = cli_json.invoke("other", app=app)

    assert_exit(result, 0)
    assert (other / "x.json").is_file()
    assert cli_json.store().list_stores() == []


def test_get_state_outside_the_envs_app_is_a_type_error() -> None:
    ctx = typer.Context(TyperCommand("plain"))

    with pytest.raises(TypeError, match="CliState"):
        get_state(ctx)


def test_repr_hides_the_connection_option_and_the_opened_store_urls(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    # A connection string may hold a password (CONTRIBUTING §6), like Settings.connection.
    option = f"json://{cli_json.root}/option-hunter2"
    other = f"json://{cli_json.root}/other-hunter2"
    seen: list[str] = []

    @app.command("show-repr", cls=EnvsCommand)
    def show_repr(ctx: typer.Context) -> None:
        state = get_state(ctx)
        state.open_store(ctx)
        state.open_store(ctx, connection=other)
        seen.append(repr(state))

    result = cli_json.invoke("-c", option, "show-repr", app=app, connection=False)

    assert_exit(result, 0)
    assert len(seen) == 1
    assert "CliState(" in seen[0]
    assert "hunter2" not in seen[0]


def test_close_stores_closes_every_opened_store_and_forgets_them(cli_json: CliHarness) -> None:
    # run closes all stores before exec, so no handle or lock leaks into the command.
    app = build_app()
    other = f"json://{cli_json.root}/other"
    seen: list[EnvironmentStore] = []

    @app.command("close", cls=EnvsCommand)
    def close(ctx: typer.Context) -> None:
        state = get_state(ctx)
        seen.extend((state.open_store(ctx), state.open_store(ctx, connection=other)))
        state.close_stores()
        assert all(store.closed for store in seen)
        seen.append(state.open_store(ctx))

    result = cli_json.invoke("close", app=app)

    assert_exit(result, 0)
    assert seen[2] is not seen[0]
    assert seen[2].closed
