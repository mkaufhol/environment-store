"""`envs export-credentials` and `ENV_STORE_LOAD` in the CLI.

The command prints the two variables a deployment needs, `ENV_STORE_CONNECTION` and
`ENV_STORE_LOAD`, after decrypting every store with its key. Reading commands take their
stores and keys from `ENV_STORE_LOAD`; `run` never passes it on.
"""

import json
from pathlib import Path
from typing import Final

from environment_store.config.load_spec import LoadSpec
from environment_store.core.secrets import Passphrase
from environment_store.library.keys import parse_key_text
from environment_store.library.store import EnvironmentStore
from tests.support.cli import CliHarness, Executed, RecordingPrompter, assert_exit

CANARY: Final = "do-not-echo-this-value"
PASSPHRASE: Final = Passphrase(text="pw")


def _arrange(cli: CliHarness) -> Path:
    """Plain 'base', key file store 'secret', passphrase store 'phrase'; returns the key file."""
    key = cli.key_file()
    library = cli.store()
    library.create_store("base")
    library.set_many("base", {"HOST": "base", "PORT": "1"})
    library.create_store("secret", encrypt=True, key=key)
    library.set_many("secret", {"HOST": "secret", "API_URL": "t"}, key=key)
    library.create_store("phrase", encrypt=True, key=PASSPHRASE)
    library.set("phrase", "WORD", "w", key=PASSPHRASE)
    return key


def _dotenv(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines())


def _spec(cli: CliHarness, key: Path) -> str:
    secret = parse_key_text(key.read_text(encoding="utf-8"))
    keys = {"secret": secret, "phrase": PASSPHRASE}
    return LoadSpec(stores=("base", "secret", "phrase"), keys=keys).encode()


# --------------------------------------------------------------------------------------------------


def test_prints_the_connection_and_the_load_spec_as_dotenv(cli: CliHarness) -> None:
    key = _arrange(cli)

    phrase = cli.passphrase_file("pw")

    result = cli.invoke(
        "export-credentials",
        "base",
        "secret",
        "phrase",
        "-k",
        f"secret={key}",
        "-k",
        f"phrase={phrase}",
    )

    assert_exit(result, 0)
    variables = _dotenv(result.stdout)
    assert list(variables) == ["ENV_STORE_CONNECTION", "ENV_STORE_LOAD"]
    assert variables["ENV_STORE_CONNECTION"] == cli.connection
    spec = LoadSpec.decode(variables["ENV_STORE_LOAD"])
    assert spec.stores == ("base", "secret", "phrase")
    assert spec.keys["secret"] == parse_key_text(key.read_text(encoding="utf-8"))
    assert spec.keys["phrase"] == PASSPHRASE


def test_json_prints_one_document(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export-credentials", "base", "--json")

    assert_exit(result, 0)
    document = json.loads(result.stdout)
    assert document["ENV_STORE_CONNECTION"] == cli_json.connection
    assert LoadSpec.decode(document["ENV_STORE_LOAD"]) == LoadSpec(stores=("base",))


def test_the_output_loads_everything_with_nothing_else_set(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    phrase = cli_json.passphrase_file("pw")
    exported = cli_json.invoke(
        "export-credentials",
        "base",
        "secret",
        "phrase",
        "-k",
        f"secret={key}",
        "-k",
        f"phrase={phrase}",
        "--json",
    )
    env = json.loads(exported.stdout)

    result = cli_json.invoke("export", "-t", "json", env=env, connection=False)

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {"API_URL": "t", "HOST": "secret", "PORT": "1", "WORD": "w"}


def test_a_first_wins_merge_order_is_carried_over(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file("ordered_overwrite = false\n")

    result = cli_json.invoke("export-credentials", "base")

    assert_exit(result, 0)
    variables = _dotenv(result.stdout)
    assert list(variables) == [
        "ENV_STORE_CONNECTION",
        "ENV_STORE_LOAD",
        "ENV_STORE_ORDERED_OVERWRITE",
    ]
    assert variables["ENV_STORE_ORDERED_OVERWRITE"] == "false"


def test_keys_come_from_the_prompt_like_any_reading_command(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    prompter = RecordingPrompter("pw")

    result = cli_json.invoke("export-credentials", "phrase", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert [prompt for _, prompt in prompter.prompts] == ["Key or passphrase for store 'phrase': "]
    assert LoadSpec.decode(_dotenv(result.stdout)["ENV_STORE_LOAD"]).keys["phrase"] == PASSPHRASE


def test_keys_come_from_the_key_variables(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    env = {"ENV_STORE_KEY_SECRET": key.read_text(encoding="utf-8"), "ENV_STORE_KEY_PHRASE": "pw"}

    result = cli_json.invoke("export-credentials", "secret", "phrase", env=env)

    assert_exit(result, 0)
    spec = LoadSpec.decode(_dotenv(result.stdout)["ENV_STORE_LOAD"])
    assert set(spec.keys) == {"secret", "phrase"}


def test_the_default_stores_come_from_the_project_file(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file('stores = ["base"]\n')

    result = cli_json.invoke("export-credentials")

    assert_exit(result, 0)
    assert LoadSpec.decode(_dotenv(result.stdout)["ENV_STORE_LOAD"]).stores == ("base",)


def test_a_wrong_key_fails_with_exit_4_and_prints_nothing(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    wrong = cli_json.passphrase_file("wrong")

    result = cli_json.invoke("export-credentials", "phrase", "-k", str(wrong))

    assert_exit(result, 4)
    assert result.stdout == ""


def test_a_missing_key_fails_with_exit_4(cli_json: CliHarness) -> None:
    _arrange(cli_json)

    result = cli_json.invoke("export-credentials", "base", "phrase")

    assert_exit(result, 4)
    assert "-k phrase=<path>" in result.stderr
    assert result.stdout == ""


def test_a_relative_connection_is_printed_as_an_absolute_one(cli_json: CliHarness) -> None:
    cli_json.store().create_store("base")
    assert Path.cwd() == cli_json.root

    result = cli_json.invoke("-c", "json://stores", "export-credentials", "base", connection=False)

    assert_exit(result, 0)
    assert _dotenv(result.stdout)["ENV_STORE_CONNECTION"] == cli_json.connection


def test_a_connection_that_dotenv_cannot_hold_asks_for_json(cli_json: CliHarness) -> None:
    connection = f"json://{cli_json.root}/it's-${{{CANARY}}}"
    with EnvironmentStore(connection, environ={}) as library:
        library.create_store("base")

    result = cli_json.invoke("-c", connection, "export-credentials", "base", connection=False)

    assert_exit(result, 1)
    assert "cannot be written as a dotenv line: use --json" in result.stderr
    assert CANARY not in result.stderr
    assert result.stdout == ""


# --- reading commands with ENV_STORE_LOAD -------------------------------------------------------


def test_reading_commands_default_to_the_spec_stores(cli: CliHarness) -> None:
    key = _arrange(cli)

    result = cli.invoke("export", "-t", "json", env={"ENV_STORE_LOAD": _spec(cli, key)})

    assert_exit(result, 0)
    assert json.loads(result.stdout) == {"API_URL": "t", "HOST": "secret", "PORT": "1", "WORD": "w"}


def test_the_spec_stores_win_over_the_project_file(cli_json: CliHarness) -> None:
    _arrange(cli_json)
    cli_json.project_file('stores = ["secret"]\n')
    spec = LoadSpec(stores=("base",)).encode()

    result = cli_json.invoke("get", "HOST", env={"ENV_STORE_LOAD": spec})

    assert_exit(result, 0)
    assert result.stdout.rstrip("\n") == "base"


def test_writing_commands_take_keys_from_the_spec(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke(
        "set", "-s", "phrase", "NEW", input="1", env={"ENV_STORE_LOAD": _spec(cli_json, key)}
    )

    assert_exit(result, 0)
    assert cli_json.store().variables("phrase", key=PASSPHRASE)["NEW"] == "1"


def test_a_key_in_both_variables_is_refused(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    env = {"ENV_STORE_LOAD": _spec(cli_json, key), "ENV_STORE_KEY_PHRASE": CANARY}

    result = cli_json.invoke("get", "WORD", "phrase", env=env)

    assert_exit(result, 1)
    assert "gets a key from both ENV_STORE_KEY_PHRASE and ENV_STORE_LOAD" in result.stderr
    assert CANARY not in result.stderr


def test_a_wrong_kind_of_secret_keeps_the_variable_message(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    secret = parse_key_text(key.read_text(encoding="utf-8"))
    spec = LoadSpec(stores=("phrase",), keys={"phrase": secret}).encode()

    result = cli_json.invoke("get", "WORD", "phrase", env={"ENV_STORE_LOAD": spec})

    assert_exit(result, 4)
    assert "ENV_STORE_LOAD holds key text for store 'phrase'" in result.stderr
    assert "-k" not in result.stderr


def test_a_malformed_spec_fails_every_command(cli_json: CliHarness) -> None:
    result = cli_json.invoke("ls-store", env={"ENV_STORE_LOAD": CANARY})

    assert_exit(result, 1)
    assert "ENV_STORE_LOAD is not a valid load specification" in result.stderr
    assert CANARY not in result.stderr


def test_an_empty_import_checks_a_key_from_the_spec(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)
    secret = parse_key_text(key.read_text(encoding="utf-8"))
    spec = LoadSpec(stores=("phrase",), keys={"phrase": secret}).encode()

    result = cli_json.invoke(
        "import", "-s", "phrase", "-t", "json", input="{}", env={"ENV_STORE_LOAD": spec}
    )

    assert_exit(result, 4)
    assert "ENV_STORE_LOAD holds key text" in result.stderr


def test_run_never_passes_the_spec_on(cli_json: CliHarness) -> None:
    key = _arrange(cli_json)

    result = cli_json.invoke(
        "run", "--", "cmd", env={"ENV_STORE_LOAD": _spec(cli_json, key), "OTHER": "kept"}
    )

    assert isinstance(result.exception, Executed)
    _, _, child = cli_json.exec_calls[0]
    assert child["WORD"] == "w"
    assert child["OTHER"] == "kept"
    assert "ENV_STORE_LOAD" not in child
