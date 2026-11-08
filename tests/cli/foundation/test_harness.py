"""The shared CLI harness itself (tests/support/cli.py), so the command tests can rely on it."""

import stat
from dataclasses import replace
from pathlib import Path

import pytest
import typer

from environment_store.cli._typer import EnvsCommand, PassthroughCommand, passthrough_args
from environment_store.cli.app import build_app
from environment_store.cli.state import get_state
from environment_store.core.adapter import MigratableAdapter, SetupMode
from environment_store.core.errors import BackendError
from environment_store.library.store import open_configured_adapter
from tests.support.cli import (
    SCHEMES,
    CliHarness,
    Executed,
    HookedAdapter,
    RecordingPrompter,
    assert_exit,
    connection_for,
    hooked,
    raising,
    temporary_cli,
)


def test_every_backend_fixture_starts_empty(cli: CliHarness) -> None:
    assert cli.store().list_stores() == []
    assert cli.connection in {connection_for(cli.root, scheme) for scheme in SCHEMES}


def test_schemes_are_json_toml_sqlite() -> None:
    assert SCHEMES == ("json", "toml", "sqlite")


def test_invoke_passes_the_connection(cli: CliHarness) -> None:
    cli.store().create_store("a")

    result = cli.invoke("migrate")

    assert result.exit_code in {0, 1}
    assert "no connection" not in result.stderr


def test_assert_exit_reports_output_and_exception(cli_json: CliHarness) -> None:
    result = cli_json.invoke("--version", connection=False)

    with pytest.raises(pytest.fail.Exception, match="expected 3"):
        assert_exit(result, 3)


def test_assert_exit_names_an_unexpected_exception(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("boom", cls=EnvsCommand)
    def boom() -> None:
        message = "bug"
        raise RuntimeError(message)

    result = cli_json.invoke("boom", app=app)

    with pytest.raises(pytest.fail.Exception, match="RuntimeError"):
        assert_exit(result, 0)


def test_recording_prompter_answers_in_order_and_records() -> None:
    prompter = RecordingPrompter("s", "n", "YES", "no")

    assert prompter.secret("Key: ") == "s"
    assert prompter.new_secret("New: ") == "n"
    assert prompter.confirm("Sure?") is True
    assert prompter.confirm("Really?") is False
    assert prompter.prompts == [
        ("secret", "Key: "),
        ("new_secret", "New: "),
        ("confirm", "Sure?"),
        ("confirm", "Really?"),
    ]
    assert prompter.remaining == 0


def test_recording_prompter_fails_the_test_when_it_runs_out() -> None:
    with pytest.raises(pytest.fail.Exception, match="unexpected secret prompt"):
        RecordingPrompter().secret("Key: ")


def test_recording_prompter_turns_end_of_input_into_abort() -> None:
    with pytest.raises(typer.Abort):
        RecordingPrompter(EOFError()).confirm("Sure?")


def test_recording_prompter_raises_other_exceptions() -> None:
    with pytest.raises(KeyboardInterrupt):
        RecordingPrompter(KeyboardInterrupt()).secret("Key: ")


def test_hooks_run_once_around_the_first_call(cli_json: CliHarness) -> None:
    calls: list[str] = []
    adapter = hooked(
        open_configured_adapter(cli_json.connection, SetupMode.AUTO),
        before={"list_stores": lambda: calls.append("before")},
        after={"list_stores": lambda: calls.append("after")},
    )

    with adapter:
        adapter.list_stores()
        adapter.list_stores()

    assert calls == ["before", "after"]


def test_hooked_adapter_delegates_every_method(cli_json: CliHarness) -> None:
    store = cli_json.store()
    store.create_store("a")
    adapter = hooked(open_configured_adapter(cli_json.connection, SetupMode.AUTO))
    record = adapter.read_store("a")

    adapter.write_store(replace(record, revision=2), expected_revision=1)
    adapter.delete_store("a")
    adapter.create_store(record)
    adapter.close()

    assert isinstance(adapter, HookedAdapter)
    assert [info.name for info in store.list_stores()] == ["a"]


def test_hooked_sql_adapter_stays_migratable(tmp_path: Path) -> None:
    adapter = hooked(
        open_configured_adapter(connection_for(tmp_path, "sqlite"), SetupMode.NONE),
        after={"migrate": raising(BackendError("after migrate"))},
    )

    assert isinstance(adapter, MigratableAdapter)
    with adapter, pytest.raises(BackendError, match="after migrate"):
        adapter.migrate()


def test_file_adapter_is_not_made_migratable(cli_json: CliHarness) -> None:
    adapter = hooked(open_configured_adapter(cli_json.connection, SetupMode.AUTO))

    with adapter:
        assert not isinstance(adapter, MigratableAdapter)


def test_hooked_opener_wraps_only_the_first_adapter(cli_json: CliHarness) -> None:
    opener = cli_json.hooked_opener()

    first = opener(cli_json.connection, SetupMode.AUTO)
    second = opener(cli_json.connection, SetupMode.AUTO)

    assert isinstance(first, HookedAdapter)
    assert not isinstance(second, HookedAdapter)
    first.close()
    second.close()


def test_fake_exec_records_and_raises(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("run", cls=PassthroughCommand)
    def run(ctx: typer.Context) -> None:
        command = passthrough_args(ctx) or []
        get_state(ctx).runtime.exec_process(command[0], command, {"A": "1"})

    result = cli_json.invoke("run", "--", "echo", "-o", app=app)

    assert isinstance(result.exception, Executed)
    assert result.exception.argv == ["echo", "-o"]
    assert cli_json.exec_calls == [("echo", ["echo", "-o"], {"A": "1"})]


def test_fake_exec_can_raise_a_chosen_error(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("run", cls=PassthroughCommand)
    def run(ctx: typer.Context) -> None:
        get_state(ctx).runtime.exec_process("nope", ["nope"], {})

    cli_json.exec_error = FileNotFoundError()

    result = cli_json.invoke("run", "--", "nope", app=app)

    assert isinstance(result.exception, FileNotFoundError)


def test_key_and_passphrase_files_are_written_in_the_root(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    phrase = cli_json.passphrase_file("pw\n")

    assert key.parent == cli_json.root
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert phrase.read_text() == "pw\n"


def test_project_file_can_be_written_in_a_subdirectory(cli_json: CliHarness) -> None:
    path = cli_json.project_file("stores = []", directory=cli_json.root / "sub")

    assert path == cli_json.root / "sub" / ".envstore.toml"


def test_harness_default_app_is_the_real_app(cli_json: CliHarness) -> None:
    result = cli_json.invoke("--help", connection=False)

    assert "migrate" in result.stdout


def test_harness_app_attribute_replaces_the_default(cli_json: CliHarness) -> None:
    app = build_app()

    @app.command("only-here", cls=EnvsCommand)
    def only_here() -> None:
        typer.echo("here")

    cli_json.app = app

    assert cli_json.invoke("only-here").stdout == "here\n"


def test_temporary_cli_gives_a_fresh_backend_per_use() -> None:
    with temporary_cli("sqlite") as first:
        first.store().create_store("a")
        root = first.root
    with temporary_cli() as second:
        assert second.store().list_stores() == []

    assert not root.exists()
