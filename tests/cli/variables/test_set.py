"""`envs set`: set variables in one store, in one write."""

from pathlib import Path

import pytest
from hypothesis import given, settings

from environment_store.config.load_spec import LoadSpec
from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, RecordingPrompter, assert_exit, temporary_cli
from tests.support.strategies import values


def _encrypted(cli: CliHarness) -> Path:
    key = cli.key_file()
    cli.store().create_store("s", encrypt=True, key=key)
    return key


def test_set_key_value_pairs_in_one_write(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    revision = library.store_info("a").revision

    result = cli.invoke("set", "-s", "a", "HOST=localhost", "PORT=5432")

    assert_exit(result, 0)
    assert cli.store().variables("a") == {"HOST": "localhost", "PORT": "5432"}
    assert cli.store().store_info("a").revision == revision + 1
    assert result.stdout == ""
    assert "HOST, PORT" in result.stderr


@pytest.mark.parametrize(
    ("argument", "expected"),
    [("EMPTY=", ""), ("URL=a=b=c", "a=b=c"), ("SPACE= x ", " x "), ("U=ünï", "ünï")],
)
def test_set_splits_at_the_first_equals_sign(
    cli_json: CliHarness, argument: str, expected: str
) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "--store", "a", argument)

    assert_exit(result, 0)
    assert list(cli_json.store().variables("a").values()) == [expected]


def test_set_refuses_existing_variables_listing_all_and_writes_nothing(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set_many("a", {"A": "old", "B": "old"})

    result = cli.invoke("set", "-s", "a", "A=new", "B=new", "C=new")

    assert_exit(result, 3)
    assert "A, B" in result.stderr
    assert "-o/--overwrite" in result.stderr
    assert "overwrite=True" not in result.stderr
    assert cli.store().variables("a") == {"A": "old", "B": "old"}


def test_set_overwrite_replaces_existing_variables(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "A", "old")

    result = cli_json.invoke("set", "-s", "a", "-o", "A=new", "B=new")

    assert_exit(result, 0)
    assert cli_json.store().variables("a") == {"A": "new", "B": "new"}


@pytest.mark.parametrize(
    "arguments",
    [("A=1", "B"), ("A", "B=1"), ("A", "B"), ("1BAD=x",), ("=x",), ("1BAD",), ("A=1", "A=2")],
)
def test_set_refuses_malformed_arguments(cli_json: CliHarness, arguments: tuple[str, ...]) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "-s", "a", *arguments, input="v")

    assert_exit(result, 1)
    assert cli_json.store().variables("a") == {}


def test_set_without_arguments_is_a_usage_error(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "-s", "a")

    assert_exit(result, 1)


def test_set_without_a_store_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke("set", "A=1")

    assert_exit(result, 1)


def test_set_in_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("set", "-s", "nope", "A=1")

    assert_exit(result, 2)


def test_set_with_an_invalid_store_name_fails(cli_json: CliHarness) -> None:
    result = cli_json.invoke("set", "-s", "Bad Name", "A=1")

    assert_exit(result, 1)


def test_set_key_value_on_an_encrypted_store_is_refused_before_reading_a_key(
    cli: CliHarness,
) -> None:
    _encrypted(cli)

    # No -k and a terminal: the refusal comes before any key prompt.
    result = cli.invoke("set", "-s", "s", "A=1", stdin_tty=True)

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert "prompt" in result.stderr


def test_set_reads_the_value_from_stdin(cli: CliHarness) -> None:
    cli.store().create_store("a")

    result = cli.invoke("set", "-s", "a", "PASSWORD", input=b"secret\n")

    assert_exit(result, 0)
    assert cli.store().get("a", "PASSWORD") == "secret"


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        (b"abc\n", "abc"),
        (b"abc\r\n", "abc"),
        (b"abc\n\n", "abc\n"),
        (b"abc\r", "abc\r"),
        (b"a\r\nb", "a\r\nb"),
        (b"abc", "abc"),
        (b"\n", ""),
    ],
)
def test_set_from_stdin_strips_exactly_one_trailing_newline(
    cli_json: CliHarness, sent: bytes, stored: str
) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "-s", "a", "X", input=sent)

    assert_exit(result, 0)
    assert cli_json.store().get("a", "X") == stored


@pytest.mark.parametrize("stdin", [b"", None])
def test_set_from_empty_stdin_is_refused_and_names_how_to_set_an_empty_value(
    cli_json: CliHarness, stdin: bytes | None
) -> None:
    # Zero bytes (< /dev/null, a forgotten pipe) never blanks a variable.
    store = cli_json.store()
    store.create_store("a")
    store.set("a", "X", "keep")

    result = cli_json.invoke("set", "-s", "a", "-o", "X", input=stdin)

    assert_exit(result, 1)
    assert "no value was read from stdin" in result.stderr
    assert "echo | envs set -s a X" in result.stderr
    assert "X=" in result.stderr
    assert cli_json.store().get("a", "X") == "keep"


def test_set_from_empty_stdin_into_an_encrypted_store_is_refused(cli_json: CliHarness) -> None:
    key = _encrypted(cli_json)

    result = cli_json.invoke("set", "-s", "s", "-k", str(key), "TOKEN", input=b"")

    assert_exit(result, 1)
    assert "no value was read from stdin" in result.stderr
    assert cli_json.store().variables("s", key=key) == {}


def test_set_from_stdin_refuses_non_utf8(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "-s", "a", "X", input=b"\xff\xfe")

    assert_exit(result, 1)
    assert "UTF-8" in result.stderr
    assert cli_json.store().variables("a") == {}


def test_set_from_stdin_refuses_a_nul_character(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("set", "-s", "a", "X", input=b"a\x00b")

    assert_exit(result, 1)


def test_set_from_stdin_into_an_encrypted_store_with_a_key_file(cli: CliHarness) -> None:
    key = _encrypted(cli)

    result = cli.invoke("set", "-s", "s", "-k", str(key), "TOKEN", input="t0k3n\n")

    assert_exit(result, 0)
    assert cli.store().get("s", "TOKEN", key=key) == "t0k3n"


def test_set_with_the_project_key(cli_json: CliHarness) -> None:
    key = _encrypted(cli_json)
    cli_json.project_file(f"[keys]\ns = '{key}'\n")

    result = cli_json.invoke("set", "-s", "s", "TOKEN", input="t")

    assert_exit(result, 0)
    assert cli_json.store().get("s", "TOKEN", key=key) == "t"


def test_set_never_takes_the_store_from_the_project_file(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    cli_json.project_file("stores = ['a']\n")

    result = cli_json.invoke("set", "A=1")

    assert_exit(result, 1)
    assert (
        "writing commands never take the store from ENV_STORE_LOAD or the project" in result.stderr
    )
    assert cli_json.store().variables("a") == {}


def test_set_never_takes_the_store_from_the_load_spec(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    spec = LoadSpec(stores=("a",)).encode()

    result = cli_json.invoke("set", "A=1", env={"ENV_STORE_LOAD": spec})

    assert_exit(result, 1)
    assert "never take the store from ENV_STORE_LOAD" in result.stderr
    assert cli_json.store().variables("a") == {}


@pytest.mark.parametrize("project", [None, "", "stores = 'not a list'"])
def test_set_without_a_store_and_without_project_stores_gives_no_project_hint(
    cli_json: CliHarness, project: str | None
) -> None:
    if project is not None:
        cli_json.project_file(project)

    result = cli_json.invoke("set", "A=1")

    assert_exit(result, 1)
    assert "Missing option" in result.stderr
    assert "project file" not in result.stderr


def test_set_from_stdin_and_a_key_from_stdin_is_refused(cli_json: CliHarness) -> None:
    key = _encrypted(cli_json)

    result = cli_json.invoke("set", "-s", "s", "-k", "-", "TOKEN", input=key.read_bytes())

    assert_exit(result, 1)
    assert "stdin" in result.stderr
    assert cli_json.store().variables("s", key=key) == {}


def test_set_with_a_wrong_key_exits_4(cli_json: CliHarness) -> None:
    _encrypted(cli_json)
    other = cli_json.key_file("other.key")

    result = cli_json.invoke("set", "-s", "s", "-k", str(other), "TOKEN", input="t")

    assert_exit(result, 4)


def test_set_without_a_key_when_not_interactive_exits_4(cli_json: CliHarness) -> None:
    _encrypted(cli_json)

    result = cli_json.invoke("set", "-s", "s", "TOKEN", input="t")

    assert_exit(result, 4)


def test_set_with_a_key_for_a_plaintext_store_fails(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    key = cli_json.key_file()

    result = cli_json.invoke("set", "-s", "a", "-k", str(key), "A=1")

    assert_exit(result, 1)
    assert cli_json.store().variables("a") == {}


def test_set_prompts_for_the_value_twice_on_a_terminal(cli: CliHarness) -> None:
    cli.store().create_store("a")
    prompter = RecordingPrompter("hidden value")

    result = cli.invoke("set", "-s", "a", "PASSWORD", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert cli.store().get("a", "PASSWORD") == "hidden value"
    assert prompter.prompts == [("new_secret", "Value of PASSWORD: ")]


def test_set_prompts_for_the_key_and_then_the_value(cli_json: CliHarness) -> None:
    cli_json.store().create_store("p", encrypt=True, key=Passphrase(text="pw"))
    prompter = RecordingPrompter("pw", "v")

    result = cli_json.invoke("set", "-s", "p", "X", stdin_tty=True, prompter=prompter)

    assert_exit(result, 0)
    assert [kind for kind, _ in prompter.prompts] == ["secret", "new_secret"]
    assert cli_json.store().get("p", "X", key=Passphrase(text="pw")) == "v"


def test_set_with_noinput_reads_stdin_even_on_a_terminal(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    # The default RecordingPrompter fails the test on any prompt.
    result = cli_json.invoke("--noinput", "set", "-s", "a", "X", input="piped\n", stdin_tty=True)

    assert_exit(result, 0)
    assert cli_json.store().get("a", "X") == "piped"


def test_set_of_an_existing_variable_fails_before_prompting(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "old")

    result = cli_json.invoke("set", "-s", "a", "X", stdin_tty=True)

    assert_exit(result, 3)
    assert cli_json.store().get("a", "X") == "old"


def test_set_overwrite_from_stdin(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "X", "old")

    result = cli_json.invoke("set", "-s", "a", "-o", "X", input="new")

    assert_exit(result, 0)
    assert cli_json.store().get("a", "X") == "new"


def test_set_with_a_concurrent_change_exits_5(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")
    opener = cli_json.hooked_opener(
        before={"write_store": lambda: cli_json.store().set("a", "RACE", "1")}
    )

    result = cli_json.invoke("set", "-s", "a", "X=1", opener=opener)

    assert_exit(result, 5)
    assert cli_json.store().variables("a") == {"RACE": "1"}


# A value ending in \r cannot round-trip this way: \r plus the appended \n is one CRLF.
@settings(max_examples=25, deadline=None)
@given(value=values().filter(lambda value: not value.endswith("\r")))
def test_any_value_piped_with_one_newline_round_trips_through_get(value: str) -> None:
    with temporary_cli() as cli:
        cli.store().create_store("a")

        written = cli.invoke("set", "-s", "a", "X", input=value.encode("utf-8") + b"\n")
        read = cli.invoke("get", "X", "a")

        assert_exit(written, 0)
        assert read.stdout_bytes == value.encode("utf-8")
