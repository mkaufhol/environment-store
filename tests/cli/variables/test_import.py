"""`envs import`: fill an existing store from a dotenv, JSON or TOML file (spec §6.10, D22, D33,
D37, PD 27, PD 34, PD 35)."""

import json
from pathlib import Path

import pytest
from hypothesis import given, reject, settings

from environment_store.core.errors import ValidationError
from environment_store.core.merge import MergeOrder
from environment_store.formats.infer import Format
from environment_store.library.environment import Environment
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, temporary_cli
from tests.support.strategies import variable_maps

_PEM = (
    "-----BEGIN PRIVATE KEY-----\nMIIBVQIBADANBgkq\nhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n"
)


def _write(cli: CliHarness, name: str, text: str) -> Path:
    path = cli.root / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (".env", "HOST=localhost\nexport PORT='5432'\n# comment\n"),
        ("vars.json", '{"HOST": "localhost", "PORT": "5432"}'),
        ("vars.toml", 'HOST = "localhost"\nPORT = "5432"\n'),
    ],
)
def test_import_infers_the_format_from_the_file_name(cli: CliHarness, name: str, text: str) -> None:
    cli.store().create_store("a")
    path = _write(cli, name, text)
    revision = cli.store().store_info("a").revision

    result = cli.invoke("import", "-s", "a", "-f", str(path))

    assert_exit(result, 0)
    assert cli.store().variables("a") == {"HOST": "localhost", "PORT": "5432"}
    assert cli.store().store_info("a").revision == revision + 1
    assert result.stdout == ""
    assert "2 variables" in result.stderr


@pytest.mark.parametrize(
    ("fmt", "text"),
    [
        ("dotenv", "A=1\n"),
        ("json", '{"A": "1"}'),
        ("toml", 'A = "1"'),
        ("JSON", '{"A": "1"}'),
    ],
)
def test_import_type_option_overrides_the_file_name(
    cli_json: CliHarness, fmt: str, text: str
) -> None:
    cli_json.store().create_store("a")
    path = _write(cli_json, "input.txt", text)

    result = cli_json.invoke("import", "-s", "a", "-f", str(path), "-t", fmt)

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "1"}


def test_import_of_a_file_whose_format_cannot_be_inferred_fails(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    path = _write(cli_json, "input.txt", "A=1\n")

    result = cli_json.invoke("import", "-s", "a", "-f", str(path))

    assert_exit(result, 1)
    assert "-t" in result.stderr
    assert cli_json.store().variables("a") == {}


def test_import_reads_dotenv_from_stdin_by_default(cli: CliHarness) -> None:
    cli.store().create_store("a")

    result = cli.invoke("import", "-s", "a", input="A=1\nB='two words'\n")

    assert_exit(result, 0)
    assert cli.store().variables("a") == {"A": "1", "B": "two words"}


def test_import_reads_stdin_for_a_dash(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-f", "-", "-t", "json", input='{"A": "1"}')

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "1"}


def test_import_keeps_crlf_inside_values_from_stdin(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-t", "json", input=b'{"A": "x\\r\\ny"}\r\n')

    assert_exit(result, 0)
    assert cli_json.store().get("a", "A") == "x\r\ny"


def test_import_never_interpolates(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", input='A=${HOME}\nB="$USER"\n')

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "${HOME}", "B": "$USER"}


def test_import_refuses_nested_json(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-t", "json", input='{"a": {"A": "1"}}')

    assert_exit(result, 1)
    assert "nested" in result.stderr
    assert cli_json.store().variables("a") == {}


def test_import_refuses_malformed_input(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-t", "toml", input="A = ")

    assert_exit(result, 1)


def test_import_refuses_non_utf8_stdin(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", input=b"A=\xff\n")

    assert_exit(result, 1)
    assert "UTF-8" in result.stderr


def test_import_refuses_a_non_utf8_file(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    path = cli_json.root / ".env"
    path.write_bytes(b"A=\xff\n")

    result = cli_json.invoke("import", "-s", "a", "-f", str(path))

    assert_exit(result, 1)
    assert "UTF-8" in result.stderr


def test_import_of_a_missing_file_fails_with_the_path(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    path = cli_json.root / "missing.env"

    result = cli_json.invoke("import", "-s", "a", "-f", str(path))

    assert_exit(result, 1)
    assert str(path) in result.stderr
    assert "Traceback" not in result.stderr


def test_import_of_a_directory_fails(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    directory = cli_json.root / "dir.env"
    directory.mkdir()

    result = cli_json.invoke("import", "-s", "a", "-f", str(directory))

    assert_exit(result, 1)
    assert str(directory) in result.stderr


def test_import_conflicts_are_listed_and_nothing_is_written(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set_many("a", {"A": "old", "B": "old"})

    result = cli.invoke("import", "-s", "a", input="A=new\nB=new\nC=new\n")

    assert_exit(result, 3)
    assert "A, B" in result.stderr
    assert cli.store().variables("a") == {"A": "old", "B": "old"}


def test_import_overwrite(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set_many("a", {"A": "old", "KEEP": "k"})

    result = cli_json.invoke("import", "-s", "a", "-o", input="A=new\nC=new\n")

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "new", "C": "new", "KEEP": "k"}


@pytest.mark.parametrize("text", ["", "# only a comment\n\n"])
def test_import_of_an_empty_document_writes_nothing(cli_json: CliHarness, text: str) -> None:
    cli_json.store().create_store("a")
    revision = cli_json.store().store_info("a").revision

    result = cli_json.invoke("import", "-s", "a", input=text)

    assert_exit(result, 0)
    assert cli_json.store().store_info("a").revision == revision
    assert "nothing to import" in result.stderr


def test_import_into_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("import", "-s", "nope", input="A=1\n")

    assert_exit(result, 2)


def test_import_into_an_encrypted_store_with_a_key(cli: CliHarness) -> None:
    key = cli.key_file()
    cli.store().create_store("s", encrypt=True, key=key)

    result = cli.invoke("import", "-s", "s", "-k", str(key), input="A=1\n")

    assert_exit(result, 0)
    assert cli.store().variables("s", key=key) == {"A": "1"}


def test_import_into_an_encrypted_store_with_a_prompted_key(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("s", encrypt=True, key=key)
    path = _write(cli_json, ".env", "A=1\n")
    prompter = RecordingPrompter(key.read_text(encoding="utf-8"))

    result = cli_json.invoke(
        "import", "-s", "s", "-f", str(path), stdin_tty=True, prompter=prompter
    )

    assert_exit(result, 0)
    assert cli_json.store().variables("s", key=key) == {"A": "1"}


def test_import_without_a_key_when_not_interactive_exits_4(cli_json: CliHarness) -> None:
    cli_json.store().create_store("s", encrypt=True, key=cli_json.key_file())

    result = cli_json.invoke("import", "-s", "s", input="A=1\n")

    assert_exit(result, 4)


def test_import_from_stdin_with_a_key_from_stdin_is_refused(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("s", encrypt=True, key=key)

    result = cli_json.invoke("import", "-s", "s", "-k", "-", input="A=1\n")

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert cli_json.store().variables("s", key=key) == {}


def test_import_from_a_file_with_a_key_from_stdin(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("s", encrypt=True, key=key)
    path = _write(cli_json, "vars.json", '{"A": "1"}')

    result = cli_json.invoke(
        "import", "-s", "s", "-f", str(path), "-k", "-", input=key.read_bytes()
    )

    assert_exit(result, 0)
    assert cli_json.store().variables("s", key=key) == {"A": "1"}


def test_import_with_a_concurrent_change_exits_5(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    opener = cli_json.hooked_opener(
        before={"write_store": lambda: cli_json.store().set("a", "RACE", "1")}
    )

    result = cli_json.invoke("import", "-s", "a", input="A=1\n", opener=opener)

    assert_exit(result, 5)
    assert cli_json.store().variables("a") == {"RACE": "1"}


@pytest.mark.parametrize(
    ("fmt", "name"), [("dotenv", ".env"), ("json", "k.json"), ("toml", "k.toml")]
)
def test_a_pem_block_ending_in_a_newline_round_trips_exactly(
    cli: CliHarness, fmt: str, name: str
) -> None:
    environment = Environment(stores=(("src", {"PEM": _PEM}),), order=MergeOrder.LAST_WINS)
    path = _write(cli, name, environment.dumps(fmt))
    cli.store().create_store("a")

    result = cli.invoke("import", "-s", "a", "-f", str(path))

    assert_exit(result, 0)
    assert cli.store().get("a", "PEM") == _PEM


@settings(max_examples=20, deadline=None)
@given(variables=variable_maps())
@pytest.mark.parametrize("fmt", list(Format))
def test_export_then_import_round_trips(fmt: Format, variables: dict[str, str]) -> None:
    environment = Environment(stores=(("src", variables),), order=MergeOrder.LAST_WINS)
    try:
        document = environment.dumps(fmt)
    except ValidationError:
        # dotenv refuses values it cannot write exactly (D37); json and toml hold everything.
        reject()
    with temporary_cli() as cli:
        cli.store().create_store("a")

        result = cli.invoke("import", "-s", "a", "-t", fmt.value, input=document.encode("utf-8"))

        assert_exit(result, 0)
        assert cli.store().variables("a") == variables


def test_import_json_document_order_does_not_matter(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke(
        "import", "-s", "a", "-t", "json", input=json.dumps({"B": "2", "A": "1"})
    )

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "1", "B": "2"}


def test_import_of_empty_stdin_with_a_key_from_stdin_is_still_refused(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-k", "-", input="")

    assert_exit(result, 1)
    assert "stdin" in result.stderr


def test_import_needs_no_key_for_an_empty_document(cli_json: CliHarness) -> None:
    cli_json.store().create_store("s", encrypt=True, key=cli_json.key_file())

    result = cli_json.invoke("import", "-s", "s", input="")

    assert_exit(result, 0)


def test_import_of_an_empty_document_refuses_a_key_for_a_plaintext_store(
    cli_json: CliHarness,
) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("import", "-s", "a", "-k", str(cli_json.key_file()), input="")

    assert_exit(result, 1)
    assert "not encrypted" in result.stderr
    assert "nothing to import" not in result.stderr


def test_import_of_an_empty_document_refuses_a_missing_key_file(cli_json: CliHarness) -> None:
    cli_json.store().create_store("s", encrypt=True, key=cli_json.key_file())
    missing = cli_json.root / "missing.key"

    result = cli_json.invoke("import", "-s", "s", "-k", str(missing), input="")

    assert_exit(result, 4)
    assert "nothing to import" not in result.stderr


def test_import_of_an_empty_document_refuses_a_project_key_for_a_plaintext_store(
    cli_json: CliHarness,
) -> None:
    cli_json.store().create_store("a")
    cli_json.project_file(f"[keys]\na = '{cli_json.key_file()}'\n")

    result = cli_json.invoke("import", "-s", "a", input="")

    assert_exit(result, 1)
    assert "[keys]" in result.stderr


def test_import_of_an_empty_document_checks_a_given_key_of_an_encrypted_store(
    cli_json: CliHarness,
) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("s", encrypt=True, key=key)
    revision = cli_json.store().store_info("s").revision

    result = cli_json.invoke("import", "-s", "s", "-k", str(key), input="")

    assert_exit(result, 0)
    assert cli_json.store().store_info("s").revision == revision
    assert "nothing to import" in result.stderr
