"""`envs mv-store`: rename or move, never zero copies (spec §6.5, D5, D7, D15, PD 33)."""

from pathlib import Path

from environment_store.core.errors import BackendError
from environment_store.core.models import KeyMode
from environment_store.library.store import EnvironmentStore
from tests.support.cli import CliHarness, assert_exit, connection_for, raising

_VARIABLES = {"HOST": "localhost", "TOKEN": "s3cret"}


def _names(cli: CliHarness) -> list[str]:
    return [info.name for info in cli.store().list_stores()]


def _plain_source(cli: CliHarness) -> None:
    store = cli.store()
    store.create_store("src")
    store.set_many("src", _VARIABLES)


def _encrypted_source(cli: CliHarness) -> Path:
    key = cli.key_file("src.key")
    store = cli.store()
    store.create_store("src", encrypt=True, key=key)
    store.set_many("src", _VARIABLES, key=key)
    return key


def test_mv_store_renames_a_store(cli: CliHarness) -> None:
    _plain_source(cli)

    result = cli.invoke("mv-store", "src", "dst")

    assert_exit(result, 0)
    assert _names(cli) == ["dst"]
    assert cli.store().variables("dst") == _VARIABLES
    assert result.stdout == ""
    assert result.stderr == "moved store 'src' to 'dst'\n"


def test_mv_store_reencrypts_with_the_same_key(cli: CliHarness) -> None:
    key = _encrypted_source(cli)

    result = cli.invoke("mv-store", "src", "dst", "-k", str(key))

    assert_exit(result, 0)
    assert _names(cli) == ["dst"]
    assert cli.store().store_info("dst").key_mode is KeyMode.KEYFILE
    assert cli.store().variables("dst", key=key) == _VARIABLES


def test_mv_store_plain_decrypts_the_moved_store(cli_json: CliHarness) -> None:
    key = _encrypted_source(cli_json)

    result = cli_json.invoke("mv-store", "src", "dst", "-k", str(key), "--plain")

    assert_exit(result, 0)
    assert cli_json.store().variables("dst") == _VARIABLES


def test_mv_store_to_another_backend_keeps_the_name(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    (cli_json.root / "other").mkdir()
    other = connection_for(cli_json.root / "other", "sqlite")

    result = cli_json.invoke("mv-store", "src", "src", "--to", other)

    assert_exit(result, 0)
    assert _names(cli_json) == []
    with EnvironmentStore(other) as target:
        assert target.variables("src") == _VARIABLES


def test_mv_store_onto_itself_without_to_fails_with_one(cli_json: CliHarness) -> None:
    _plain_source(cli_json)

    result = cli_json.invoke("mv-store", "src", "src")

    assert_exit(result, 1)
    assert _names(cli_json) == ["src"]


def test_mv_store_onto_an_existing_store_fails_with_three_and_keeps_the_source(
    cli: CliHarness,
) -> None:
    _plain_source(cli)
    cli.store().create_store("dst")

    result = cli.invoke("mv-store", "src", "dst")

    assert_exit(result, 3)
    assert cli.store().variables("src") == _VARIABLES
    assert cli.store().variables("dst") == {}


def test_mv_store_with_existing_target_removes_the_generated_key_file(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)
    cli_json.store().create_store("dst")
    key = cli_json.root / "generated.key"

    result = cli_json.invoke("mv-store", "src", "dst", "--generate-key", str(key))

    assert_exit(result, 3)
    assert not key.exists()
    assert _names(cli_json) == ["dst", "src"]


def test_mv_store_when_the_source_changes_fails_with_five_and_keeps_the_source(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)
    opener = cli_json.hooked_opener(
        before={"create_store": lambda: cli_json.store().set("src", "RACE", "1")}
    )

    result = cli_json.invoke("mv-store", "src", "dst", opener=opener)

    assert_exit(result, 5)
    assert _names(cli_json) == ["src"]
    assert cli_json.store().variables("src") == {**_VARIABLES, "RACE": "1"}


def test_mv_store_keeps_the_generated_key_when_deleting_the_source_fails(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)
    key = cli_json.root / "generated.key"
    opener = cli_json.hooked_opener(before={"delete_store": raising(BackendError("lost"))})

    result = cli_json.invoke("mv-store", "src", "dst", "--generate-key", str(key), opener=opener)

    assert_exit(result, 1)
    assert key.exists()
    assert str(key) in result.stderr
    assert cli_json.store().variables("dst", key=key) == _VARIABLES
    assert _names(cli_json) == ["dst", "src"]


def test_mv_store_new_key_from_stdin(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    key = cli_json.key_file("new.key")

    result = cli_json.invoke(
        "mv-store", "src", "dst", "--new-key", "-", input=key.read_text(encoding="utf-8")
    )

    assert_exit(result, 0)
    assert _names(cli_json) == ["dst"]
    assert cli_json.store().variables("dst", key=key) == _VARIABLES


def test_mv_store_generate_key_to_stdout_is_refused_with_a_new_key_hint(
    cli_json: CliHarness,
) -> None:
    _plain_source(cli_json)

    result = cli_json.invoke("mv-store", "src", "dst", "--generate-key", "-")

    assert_exit(result, 1)
    # PD 24: the hint names mv-store's own key file option, not -k (the source key).
    assert "'--new-key -'" in result.stderr
    assert "'-k -'" not in result.stderr
    assert not (cli_json.root / "-").exists()
    assert _names(cli_json) == ["src"]


def test_mv_store_target_encryption_options_name_new_key(cli_json: CliHarness) -> None:
    _plain_source(cli_json)
    cli_json.key_file("new.key")

    result = cli_json.invoke("mv-store", "src", "dst", "--plain", "--new-key", "new.key")

    assert_exit(result, 1)
    assert "only one" in result.stderr
    assert "--new-key" in result.stderr
    assert _names(cli_json) == ["src"]
