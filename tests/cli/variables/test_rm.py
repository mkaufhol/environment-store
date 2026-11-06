"""`envs rm`: delete variables from one store, in one write (spec §6.9, PD 26)."""

from tests.support.cli import CliHarness, assert_exit


def test_rm_deletes_several_variables_in_one_write(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set_many("a", {"A": "1", "B": "2", "C": "3"})
    revision = library.store_info("a").revision

    result = cli.invoke("rm", "-s", "a", "A", "C")

    assert_exit(result, 0)
    assert cli.store().variables("a") == {"B": "2"}
    assert cli.store().store_info("a").revision == revision + 1
    assert result.stdout == ""
    assert "A, C" in result.stderr


def test_rm_asks_no_confirmation(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "A", "1")

    # The default RecordingPrompter fails the test on any prompt.
    result = cli_json.invoke("rm", "-s", "a", "A", stdin_tty=True)

    assert_exit(result, 0)


def test_rm_of_missing_variables_lists_all_and_deletes_nothing(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("a")
    library.set("a", "A", "1")

    result = cli.invoke("rm", "-s", "a", "A", "X", "Y")

    assert_exit(result, 2)
    assert "X, Y" in result.stderr
    assert cli.store().variables("a") == {"A": "1"}


def test_rm_from_an_encrypted_store_with_a_key(cli: CliHarness) -> None:
    key = cli.key_file()
    library = cli.store()
    library.create_store("s", encrypt=True, key=key)
    library.set_many("s", {"A": "1", "B": "2"}, key=key)

    result = cli.invoke("rm", "-s", "s", "-k", str(key), "A")

    assert_exit(result, 0)
    assert cli.store().variables("s", key=key) == {"B": "2"}


def test_rm_from_an_encrypted_store_with_the_key_from_stdin(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    library = cli_json.store()
    library.create_store("s", encrypt=True, key=key)
    library.set("s", "A", "1", key=key)

    result = cli_json.invoke("rm", "-s", "s", "-k", "-", "A", input=key.read_bytes())

    assert_exit(result, 0)
    assert cli_json.store().variables("s", key=key) == {}


def test_rm_without_a_key_when_not_interactive_exits_4(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    library = cli_json.store()
    library.create_store("s", encrypt=True, key=key)
    library.set("s", "A", "1", key=key)

    result = cli_json.invoke("rm", "-s", "s", "A")

    assert_exit(result, 4)
    assert cli_json.store().variables("s", key=key) == {"A": "1"}


def test_rm_validates_names_before_reading_a_key(cli_json: CliHarness) -> None:
    key = cli_json.key_file()
    cli_json.store().create_store("s", encrypt=True, key=key)

    result = cli_json.invoke("rm", "-s", "s", "1BAD", stdin_tty=True)

    assert_exit(result, 1)
    assert "invalid variable name" in result.stderr


def test_rm_from_a_missing_store_exits_2(cli_json: CliHarness) -> None:
    result = cli_json.invoke("rm", "-s", "nope", "A")

    assert_exit(result, 2)


def test_rm_without_names_is_a_usage_error(cli_json: CliHarness) -> None:
    cli_json.store().create_store("a")

    result = cli_json.invoke("rm", "-s", "a")

    assert_exit(result, 1)


def test_rm_with_a_concurrent_change_exits_5(cli_json: CliHarness) -> None:
    library = cli_json.store()
    library.create_store("a")
    library.set("a", "A", "1")
    opener = cli_json.hooked_opener(
        before={"write_store": lambda: cli_json.store().set("a", "RACE", "1")}
    )

    result = cli_json.invoke("rm", "-s", "a", "A", opener=opener)

    assert_exit(result, 5)
    assert cli_json.store().variables("a") == {"A": "1", "RACE": "1"}
