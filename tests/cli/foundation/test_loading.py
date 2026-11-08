"""`load_for_reading`: store lists, keys, order of work."""

from pathlib import Path

import pytest
import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.loading import load_for_reading
from environment_store.cli.options import FirstWinsOpt, ReadKeysOpt, StoresArg
from environment_store.cli.output import out
from environment_store.config.settings import ENV_ORDERED_OVERWRITE
from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.secrets import Passphrase
from environment_store.library.store import open_configured_adapter
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit


@pytest.fixture
def app() -> typer.Typer:
    app = build_app()

    @app.command("show", cls=EnvsCommand)
    def show(
        ctx: typer.Context,
        stores: StoresArg = None,
        *,
        keys: ReadKeysOpt = None,
        first_wins: FirstWinsOpt = False,
    ) -> None:
        environment = load_for_reading(ctx, stores=stores, keys=keys, first_wins=first_wins)
        for name, (value, store) in environment.with_sources().items():
            out(f"{name}={value} ({store})")

    return app


def _arrange(cli: CliHarness) -> Path:
    """Plain 'base', key file store 'secret', passphrase store 'phrase'; returns the key file."""
    key = cli.key_file()
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"HOST": "base", "PORT": "1"})
    library.create_store("secret", encrypt=True, key=key)
    library.set_many("secret", {"HOST": "secret", "TOKEN": "t"}, key=key)
    library.create_store("phrase", encrypt=True, key=Passphrase(text="pw"))
    library.set("phrase", "HOST", "phrase", key=Passphrase(text="pw"))
    return key


def test_positional_stores_are_merged_last_wins(cli: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli)
    result = cli.invoke("show", "base", "secret", "-k", f"secret={stores}", app=app)

    assert_exit(result, 0)
    assert result.stdout == "HOST=secret (secret)\nPORT=1 (base)\nTOKEN=t (secret)\n"


def test_first_wins_option(cli: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli)
    result = cli.invoke("show", "base", "secret", "-k", f"secret={stores}", "--first-wins", app=app)

    assert result.stdout.startswith("HOST=base (base)\n")


def test_ordered_overwrite_false_in_the_environment(cli_json: CliHarness, app: typer.Typer) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "a")
    library.create_store("b")
    library.set("b", "X", "b")

    result = cli_json.invoke("show", "a", "b", app=app, env={ENV_ORDERED_OVERWRITE: "false"})

    assert result.stdout == "X=a (a)\n"


def test_project_stores_are_the_default_list(cli_json: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli_json)
    cli_json.project_file(f"stores = ['base', 'secret']\n[keys]\nsecret = '{stores.name}'")

    result = cli_json.invoke("show", app=app)

    assert_exit(result, 0)
    assert "HOST=secret (secret)" in result.stdout


def test_positional_stores_replace_the_project_list(cli_json: CliHarness, app: typer.Typer) -> None:
    _arrange(cli_json)
    cli_json.project_file("stores = ['secret']")

    result = cli_json.invoke("show", "base", app=app)

    assert_exit(result, 0)
    assert result.stdout == "HOST=base (base)\nPORT=1 (base)\n"


def test_no_stores_anywhere_exits_with_one(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("show", app=app)

    assert_exit(result, 1)
    assert "stores" in result.stderr
    assert ".envstore.toml" in result.stderr


def test_invalid_store_name_exits_with_one_before_opening_the_backend(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    opened: list[str] = []

    def opener(url: str, setup: SetupMode) -> Adapter:
        opened.append(url)
        return open_configured_adapter(url, setup)

    result = cli_json.invoke("show", "base", "Bad Name", app=app, opener=opener)

    assert_exit(result, 1)
    assert "invalid store name" in result.stderr
    assert opened == []


def test_key_option_errors_exit_with_one_before_opening_the_backend(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("show", "base", "-k", "other=x.key", app=app)

    assert_exit(result, 1)
    assert "not in the store list" in result.stderr


def test_all_stores_must_exist_before_any_prompt(cli_json: CliHarness, app: typer.Typer) -> None:
    _arrange(cli_json)
    result = cli_json.invoke("show", "secret", "nope", "gone", app=app, stdin_tty=True)

    assert_exit(result, 2)
    assert "store 'nope' not found in " in result.stderr
    assert "store 'gone' not found in " in result.stderr


def test_repeated_store_is_prompted_once(cli_json: CliHarness, app: typer.Typer) -> None:
    _arrange(cli_json)
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke(
        "show", "phrase", "base", "phrase", app=app, stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert prompter.prompts == [("secret", "Key or passphrase for store 'phrase': ")]
    assert result.stdout.startswith("HOST=phrase (phrase)\n")


def test_prompts_follow_the_load_order(cli_json: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli_json)
    prompter = RecordingPrompter("pw", stores.read_text())

    result = cli_json.invoke("show", "phrase", "secret", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert [text for _, text in prompter.prompts] == [
        "Key or passphrase for store 'phrase': ",
        "Key or passphrase for store 'secret': ",
    ]


def test_wrong_prompted_key_exits_with_four_without_asking_again(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    _arrange(cli_json)
    prompter = RecordingPrompter("wrong")

    result = cli_json.invoke("show", "phrase", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 4)
    assert len(prompter.prompts) == 1


@pytest.mark.parametrize(("noinput", "stdin_tty"), [(True, True), (False, False)])
def test_without_prompting_a_missing_key_exits_with_four(
    cli_json: CliHarness, app: typer.Typer, *, noinput: bool, stdin_tty: bool
) -> None:
    _arrange(cli_json)
    args = ["--noinput", "show", "secret"] if noinput else ["show", "secret"]

    result = cli_json.invoke(*args, app=app, stdin_tty=stdin_tty)

    assert_exit(result, 4)
    assert "-k" in result.stderr


def test_missing_key_with_several_stores_hints_the_store_bound_form(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("show", "base", "phrase", app=app)

    assert_exit(result, 4)
    assert "store 'phrase' is encrypted" in result.stderr
    assert "-k phrase=<path> (or -k phrase=- for stdin)" in result.stderr
    assert "-k <path>" not in result.stderr


def test_missing_key_with_one_store_repeated_keeps_the_shorthand_hint(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("show", "phrase", "phrase", app=app)

    assert_exit(result, 4)
    assert "-k <path> (or -k - for stdin)" in result.stderr


def test_key_option_beats_project_key_beats_prompt(cli_json: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli_json)
    cli_json.project_file("[keys]\nsecret = 'missing.key'\nphrase = 'p.txt'")
    cli_json.passphrase_file("pw\n")
    prompter = RecordingPrompter()

    result = cli_json.invoke(
        "show",
        "secret",
        "phrase",
        "-k",
        f"secret={stores}",
        app=app,
        stdin_tty=True,
        prompter=prompter,
    )

    assert_exit(result, 0)
    assert prompter.prompts == []


def test_shorthand_key_for_one_store(cli_json: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli_json)
    result = cli_json.invoke("show", "secret", "-k", str(stores), app=app)

    assert_exit(result, 0)


def test_store_key_from_stdin(cli_json: CliHarness, app: typer.Typer) -> None:
    stores = _arrange(cli_json)
    result = cli_json.invoke(
        "show", "base", "secret", "-k", "secret=-", app=app, input=stores.read_bytes()
    )

    assert_exit(result, 0)
    assert "TOKEN=t (secret)" in result.stdout


def test_key_option_for_a_plaintext_store_exits_with_one(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    stores = _arrange(cli_json)
    result = cli_json.invoke("show", "base", "-k", f"base={stores}", app=app)

    assert_exit(result, 1)
    assert "not encrypted" in result.stderr


def test_project_key_for_a_loaded_plaintext_store_exits_with_one(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    stores = _arrange(cli_json)
    project = cli_json.project_file(f"[keys]\nbase = '{stores.name}'")

    result = cli_json.invoke("show", "base", app=app)

    assert_exit(result, 1)
    assert str(project) in result.stderr


def test_project_keys_of_stores_not_loaded_are_ignored(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    _arrange(cli_json)
    cli_json.project_file("[keys]\nsecret = 'missing.key'\nother = 'x.key'")

    result = cli_json.invoke("show", "base", app=app)

    assert_exit(result, 0)


def test_wrong_key_file_exits_with_four(cli_json: CliHarness, app: typer.Typer) -> None:
    _arrange(cli_json)
    other = cli_json.key_file("other.key")

    result = cli_json.invoke("show", "secret", "-k", str(other), app=app)

    assert_exit(result, 4)
