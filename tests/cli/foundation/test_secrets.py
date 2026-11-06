"""Secrets for commands: existing, new and generated keys (D3, PD 5, PD 24, PD 33)."""

import stat
from pathlib import Path
from typing import Annotated, Final

import pytest
import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.app import build_app
from environment_store.cli.options import GenerateKeyOpt, NewKeyOpt, PassphraseOpt, WriteKeyOpt
from environment_store.cli.output import out
from environment_store.cli.secrets import (
    existing_secret,
    keep_or_discard,
    new_secret,
    new_secret_choice,
)
from environment_store.cli.state import get_state
from environment_store.config.secrets import GenerateKeyFile, KeyFile, NewKeyFile, NewPassphrase
from environment_store.core.errors import (
    BackendError,
    ConcurrentModificationError,
    ConfigurationError,
    DecryptionError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
    VariableExistsError,
)
from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, raising

_ERRORS: Final[dict[str, BaseException]] = {
    "validation": ValidationError("bad"),
    "configuration": ConfigurationError("bad"),
    "not-found": StoreNotFoundError("missing"),
    "key": DecryptionError("wrong key"),
    "conflict": ConcurrentModificationError("changed"),
    "variable-exists": VariableExistsError(["A"], store="t"),
    "store-exists": StoreExistsError("store 't' already exists"),
    "backend": BackendError("connection lost"),
    "bug": RuntimeError("bug"),
}


def _test_app() -> typer.Typer:
    app = build_app()

    @app.command("show", cls=EnvsCommand)
    def show(ctx: typer.Context, store: str, *, key: WriteKeyOpt = None) -> None:
        secret = existing_secret(ctx, store, key)
        variables = get_state(ctx).open_store(ctx).variables(store, key=secret)
        out(" ".join(f"{name}={value}" for name, value in variables.items()))

    @app.command("new", cls=EnvsCommand)
    def new(
        ctx: typer.Context,
        *,
        key: NewKeyOpt = None,
        generate: GenerateKeyOpt = None,
        passphrase: PassphraseOpt = False,
    ) -> None:
        chosen = new_secret(
            ctx, key=key, generate=generate, passphrase=passphrase, key_option="--new-key"
        )
        if chosen is None:
            out("none")
        else:
            out(f"{type(chosen.secret).__name__} {chosen.generated}")

    @app.command("guarded", cls=EnvsCommand)
    def guarded(
        ctx: typer.Context,
        error: str,
        *,
        generate: GenerateKeyOpt = None,
        creates: Annotated[bool, typer.Option("--creates")] = False,
        create_target: Annotated[bool, typer.Option("--create-target")] = False,
    ) -> None:
        store = get_state(ctx).open_store(ctx)
        chosen = new_secret(ctx, key=None, generate=generate, passphrase=False, key_option="-k")
        with keep_or_discard(chosen, target="t", store=store, creates_target=creates):
            if create_target:
                store.create_store("t")
            if error != "none":
                raise _ERRORS[error]
        out("done")

    return app


@pytest.fixture
def app() -> typer.Typer:
    return _test_app()


@pytest.fixture
def encrypted(cli_json: CliHarness) -> Path:
    """Store 'a' encrypted with a key file; returns the key file."""
    path = cli_json.key_file()
    store = cli_json.store()
    store.create_store("a", encrypt=True, key=path)
    store.set("a", "HOST", "db", key=path)
    return path


# --- existing secrets: -k > [keys] > prompt (D3, PD 5) -------------------------------------------


def test_key_option_reads_the_key_file(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    result = cli_json.invoke("show", "a", "-k", str(encrypted), app=app)

    assert_exit(result, 0)
    assert result.stdout == "HOST=db\n"


def test_key_option_dash_reads_stdin(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    result = cli_json.invoke("show", "a", "-k", "-", app=app, input=encrypted.read_bytes())

    assert_exit(result, 0)
    assert result.stdout == "HOST=db\n"


def test_project_key_is_used_without_key_option(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    cli_json.project_file(f"[keys]\na = '{encrypted.name}'")

    result = cli_json.invoke("show", "a", app=app)

    assert_exit(result, 0)
    assert result.stdout == "HOST=db\n"


def test_key_option_beats_the_project_key(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    cli_json.project_file("[keys]\na = 'missing.key'")

    result = cli_json.invoke("show", "a", "-k", str(encrypted), app=app)

    assert_exit(result, 0)


def test_encrypted_store_without_any_key_prompts_on_a_terminal(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    prompter = RecordingPrompter(encrypted.read_text())

    result = cli_json.invoke("show", "a", app=app, stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert prompter.prompts == [("secret", "Key or passphrase for store 'a': ")]


@pytest.mark.parametrize("noinput", [True, False])
def test_encrypted_store_without_key_and_without_prompt_exits_with_four(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path, *, noinput: bool
) -> None:
    args = ["--noinput", "show", "a"] if noinput else ["show", "a"]

    result = cli_json.invoke(*args, app=app, stdin_tty=noinput)

    assert_exit(result, 4)
    assert "-k" in result.stderr
    assert encrypted.exists()


def test_key_option_for_a_plaintext_store_exits_with_one(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    cli_json.store().create_store("p")

    result = cli_json.invoke("show", "p", "-k", str(cli_json.key_file()), app=app)

    assert_exit(result, 1)
    assert "not encrypted" in result.stderr


def test_project_key_for_a_plaintext_store_exits_with_one_naming_the_project_file(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    cli_json.store().create_store("p")
    project = cli_json.project_file("[keys]\np = 'p.key'")

    result = cli_json.invoke("show", "p", app=app)

    assert_exit(result, 1)
    assert str(project) in result.stderr


def test_plaintext_store_needs_no_key(cli_json: CliHarness, app: typer.Typer) -> None:
    cli_json.store().create_store("p")
    cli_json.store().set("p", "A", "1")

    result = cli_json.invoke("show", "p", app=app)

    assert result.stdout == "A=1\n"


def test_missing_store_exits_with_two_before_prompting(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("show", "nope", app=app, stdin_tty=True)

    assert_exit(result, 2)


def test_missing_key_file_exits_with_four(
    cli_json: CliHarness, app: typer.Typer, encrypted: Path
) -> None:
    result = cli_json.invoke("show", "a", "-k", str(encrypted.parent / "gone.key"), app=app)

    assert_exit(result, 4)
    assert "gone.key" in result.stderr


def test_empty_key_option_exits_with_one(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("show", "a", "-k", "", app=app)

    assert_exit(result, 1)


# --- new secrets (PD 24) -------------------------------------------------------------------------


def test_no_new_secret_option_gives_none(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("new", app=app)

    assert result.stdout == "none\n"


@pytest.mark.parametrize(
    "args",
    [
        ["--new-key", "a.key", "--passphrase"],
        ["--new-key", "a.key", "--generate-key", "b.key"],
        ["--generate-key", "b.key", "--passphrase"],
    ],
)
def test_more_than_one_new_secret_option_exits_with_one(
    cli_json: CliHarness, app: typer.Typer, args: list[str]
) -> None:
    result = cli_json.invoke("new", *args, app=app)

    assert_exit(result, 1)
    assert "only one of --new-key, --generate-key, --passphrase" in result.stderr
    assert not (cli_json.root / "b.key").exists()


def test_empty_new_key_names_the_new_key_option(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("new", "--new-key", "", app=app)

    assert_exit(result, 1)
    assert "the path of --new-key is empty" in result.stderr
    assert "of -k" not in result.stderr


@pytest.mark.parametrize("value", ["", "."])
def test_generate_key_without_a_file_path_is_a_usage_error(
    cli_json: CliHarness, app: typer.Typer, value: str
) -> None:
    result = cli_json.invoke("new", "--generate-key", value, app=app)

    assert_exit(result, 1)
    assert "--generate-key needs a file path" in result.stderr
    assert "already exists" not in result.stderr


def test_generate_key_to_stdout_is_refused_with_the_keygen_hint(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("new", "--generate-key", "-", app=app)

    assert_exit(result, 1)
    assert "envs keygen -" in result.stderr
    assert "--new-key -" in result.stderr
    assert not (cli_json.root / "-").exists()
    assert result.stdout == ""


def test_new_key_file_is_read(cli_json: CliHarness, app: typer.Typer) -> None:
    path = cli_json.key_file()

    result = cli_json.invoke("new", "--new-key", str(path), app=app)

    assert result.stdout == "KeyMaterial None\n"


def test_new_key_from_stdin(cli_json: CliHarness, app: typer.Typer) -> None:
    key = cli_json.key_file().read_bytes()

    result = cli_json.invoke("new", "--new-key", "-", app=app, input=key)

    assert result.stdout == "KeyMaterial None\n"


def test_new_key_that_is_not_a_key_file_exits_with_four(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path = cli_json.passphrase_file("just a passphrase\n")

    result = cli_json.invoke("new", "--new-key", str(path), app=app)

    assert_exit(result, 4)


def test_generated_key_file_is_written_with_mode_0600(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path = cli_json.root / "new.key"

    result = cli_json.invoke("new", "--generate-key", str(path), app=app)

    assert_exit(result, 0)
    assert result.stdout == f"KeyMaterial {path}\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_generated_key_file_never_overwrites(cli_json: CliHarness, app: typer.Typer) -> None:
    path = cli_json.passphrase_file("keep me")

    result = cli_json.invoke("new", "--generate-key", str(path), app=app)

    assert_exit(result, 1)
    assert path.read_text() == "keep me"


def test_piped_passphrase_is_read_from_stdin(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("new", "--passphrase", app=app, input="pw\n")

    assert result.stdout == "Passphrase None\n"


def test_passphrase_on_a_terminal_is_asked_twice(cli_json: CliHarness, app: typer.Typer) -> None:
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke("new", "--passphrase", app=app, stdin_tty=True, prompter=prompter)

    assert result.stdout == "Passphrase None\n"
    assert prompter.prompts == [("new_secret", "New passphrase: ")]


def test_passphrase_on_a_terminal_with_noinput_exits_with_four_without_reading_stdin(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("--noinput", "new", "--passphrase", app=app, stdin_tty=True)

    assert_exit(result, 4)


def test_passphrase_store_secret_resolves_from_a_passphrase_file(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    store = cli_json.store()
    store.create_store("p", encrypt=True, key=Passphrase(text="pw"))
    store.set("p", "A", "1", key=Passphrase(text="pw"))

    result = cli_json.invoke("show", "p", "-k", str(cli_json.passphrase_file("pw\n")), app=app)

    assert result.stdout == "A=1\n"


# --- keep_or_discard (PD 33) ---------------------------------------------------------------------


def _guarded(cli: CliHarness, app: typer.Typer, *args: str) -> tuple[Path, str, int]:
    path = cli.root / "gen.key"
    result = cli.invoke("guarded", *args, "--generate-key", str(path), app=app)
    return path, result.stderr, result.exit_code


@pytest.mark.parametrize(
    "error", ["validation", "configuration", "not-found", "key", "conflict", "variable-exists"]
)
def test_generated_key_is_removed_after_an_error_raised_before_any_write(
    cli_json: CliHarness, app: typer.Typer, error: str
) -> None:
    path, stderr, _ = _guarded(cli_json, app, error)

    assert not path.exists()
    assert "kept generated key file" not in stderr


@pytest.mark.parametrize("error", ["backend", "bug"])
def test_generated_key_is_kept_and_named_after_a_possibly_committed_failure(
    cli_json: CliHarness, app: typer.Typer, error: str
) -> None:
    path, stderr, _ = _guarded(cli_json, app, error)

    assert path.exists()
    assert f"kept generated key file '{path}'; store 't' may already be encrypted" in stderr


def test_backend_error_keeps_the_key_and_exits_with_one(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    _, stderr, code = _guarded(cli_json, app, "backend")

    assert code == 1
    assert stderr.endswith("Error: connection lost\n")


def test_success_keeps_the_generated_key_silently(cli_json: CliHarness, app: typer.Typer) -> None:
    path, stderr, code = _guarded(cli_json, app, "none")

    assert code == 0
    assert path.exists()
    assert stderr == ""


def test_creating_command_keeps_the_key_when_the_target_exists_afterwards(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path, stderr, _ = _guarded(cli_json, app, "validation", "--creates", "--create-target")

    assert path.exists()
    assert "kept generated key file" in stderr


def test_creating_command_removes_the_key_when_the_target_does_not_exist(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path, _, _ = _guarded(cli_json, app, "validation", "--creates")

    assert not path.exists()


def test_creating_command_removes_the_key_when_the_target_was_someone_elses(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    cli_json.store().create_store("t")

    path, _, code = _guarded(cli_json, app, "store-exists", "--creates")

    assert code == 3
    assert not path.exists()


def test_creating_command_keeps_the_key_when_the_target_check_fails(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    path = cli_json.root / "gen.key"
    opener = cli_json.hooked_opener(before={"list_stores": raising(BackendError("gone"))})

    result = cli_json.invoke(
        "guarded", "validation", "--creates", "--generate-key", str(path), app=app, opener=opener
    )

    assert_exit(result, 1)
    assert path.exists()
    assert "kept generated key file" in result.stderr


def test_failure_to_remove_the_key_is_reported_and_the_original_error_wins(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    keys = cli_json.root / "keys"
    keys.mkdir()
    path = keys / "gen.key"

    @app.command("locked", cls=EnvsCommand)
    def locked(ctx: typer.Context) -> None:
        store = get_state(ctx).open_store(ctx)
        chosen = new_secret(ctx, key=None, generate=path, passphrase=False, key_option="-k")
        keys.chmod(0o500)
        with keep_or_discard(chosen, target="t", store=store, creates_target=False):
            raise _ERRORS["validation"]

    try:
        result = cli_json.invoke("locked", app=app)
    finally:
        keys.chmod(0o700)

    assert_exit(result, 1)
    assert f"cannot remove generated key file '{path}'" in result.stderr
    assert result.stderr.endswith("Error: bad\n")


def test_without_a_new_secret_errors_pass_through(cli_json: CliHarness, app: typer.Typer) -> None:
    result = cli_json.invoke("guarded", "not-found", app=app)

    assert_exit(result, 2)
    assert "kept" not in result.stderr


# --- new_secret_choice ---------------------------------------------------------------------------


def test_new_secret_choice_without_an_option_is_none() -> None:
    assert new_secret_choice(key=None, generate=None, passphrase=False, key_option="-k") is None


def test_new_secret_choice_names_the_chosen_option(tmp_path: Path) -> None:
    key = tmp_path / "k.key"

    assert new_secret_choice(
        key=str(key), generate=None, passphrase=False, key_option="-k"
    ) == NewKeyFile(KeyFile(key))
    assert new_secret_choice(
        key=None, generate=key, passphrase=False, key_option="-k"
    ) == GenerateKeyFile(key)
    assert (
        new_secret_choice(key=None, generate=None, passphrase=True, key_option="-k")
        == NewPassphrase()
    )


@pytest.mark.parametrize(
    ("key", "generate", "match"),
    [
        ("a.key", Path("b.key"), "use only one of --new-key, --generate-key, --passphrase"),
        (None, Path("-"), "'envs keygen -' and pass it with '--new-key -'"),
        (None, Path(), "--generate-key needs a file path"),
        ("", None, "the path of --new-key is empty"),
    ],
)
def test_new_secret_choice_refuses_unusable_options(
    key: str | None, generate: Path | None, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        new_secret_choice(key=key, generate=generate, passphrase=False, key_option="--new-key")
