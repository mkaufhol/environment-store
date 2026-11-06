"""`envs ls-store`: names and encryption, never contents (spec §6.2, §4.1, D1, PD 23)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from environment_store.cli.stores.listing import encryption_label
from environment_store.core.models import KeyMode, StoreInfo
from environment_store.core.secrets import Passphrase
from tests.support.cli import CliHarness, assert_exit

_WHEN = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


def _arrange_three_stores(cli: CliHarness) -> None:
    store = cli.store()
    store.create_store("plain_one")
    store.set("plain_one", "HOST", "localhost")
    store.create_store("with_key", encrypt=True, key=cli.key_file())
    store.set("with_key", "TOKEN", "t", key=cli.root / "a.key")
    store.create_store("with_pass", encrypt=True, key=Passphrase(text="pw"))


def test_ls_store_lists_every_store_with_its_encryption(cli: CliHarness) -> None:
    _arrange_three_stores(cli)

    result = cli.invoke("ls-store")

    assert_exit(result, 0)
    assert result.stdout == (
        "name       encryption\n"
        "plain_one  plain\n"
        "with_key   encrypted (keyfile)\n"
        "with_pass  encrypted (passphrase)\n"
    )
    assert result.stderr == ""


def test_ls_store_never_shows_a_variable_count_or_names(cli_json: CliHarness) -> None:
    _arrange_three_stores(cli_json)

    result = cli_json.invoke("ls-store")

    assert_exit(result, 0)
    assert "TOKEN" not in result.stdout
    assert "HOST" not in result.stdout
    assert "1" not in result.stdout


def _location(cli: CliHarness) -> Path:
    return cli.root / ("envs.db" if cli.connection.startswith("sqlite") else "stores")


def test_ls_store_on_an_empty_backend_prints_nothing_and_names_the_location(
    cli: CliHarness,
) -> None:
    # D42: a mistyped connection must not look like an empty backend.
    result = cli.invoke("ls-store")

    assert_exit(result, 0)
    assert result.stdout == ""
    assert result.stderr == f"no stores in {_location(cli)}\n"


def test_ls_store_json_on_an_empty_backend_prints_an_empty_list(cli: CliHarness) -> None:
    result = cli.invoke("ls-store", "--json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == []
    assert result.stderr == f"no stores in {_location(cli)}\n"


def test_ls_store_with_a_relative_connection_names_the_absolute_directory(
    cli_json: CliHarness,
) -> None:
    result = cli_json.invoke("-c", "json://typo", "ls-store", connection=False)

    assert_exit(result, 0)
    assert result.stderr == f"no stores in {Path.cwd() / 'typo'}\n"


def test_ls_store_json_lists_metadata_with_utc_timestamps(cli: CliHarness) -> None:
    _arrange_three_stores(cli)
    infos = {info.name: info for info in cli.store().list_stores()}

    result = cli.invoke("ls-store", "--json")

    assert_exit(result, 0)
    document = json.loads(result.stdout)
    assert [entry["name"] for entry in document] == ["plain_one", "with_key", "with_pass"]
    assert document[0] == {
        "name": "plain_one",
        "encrypted": False,
        "key_mode": None,
        "revision": 2,
        "created_at": "2026-11-06T10:00:00Z",
        "updated_at": infos["plain_one"].updated_at.isoformat().replace("+00:00", "Z"),
    }
    assert document[1]["encrypted"] is True
    assert document[1]["key_mode"] == "keyfile"
    assert document[2]["key_mode"] == "passphrase"
    assert document[2]["revision"] == 1
    assert all(entry["updated_at"].endswith("Z") for entry in document)


def test_ls_store_json_on_an_empty_backend_is_an_empty_list(cli_json: CliHarness) -> None:
    result = cli_json.invoke("ls-store", "--json")

    assert_exit(result, 0)
    assert json.loads(result.stdout) == []


def test_ls_store_needs_no_key_and_never_prompts(cli_json: CliHarness) -> None:
    _arrange_three_stores(cli_json)

    result = cli_json.invoke("ls-store", stdin_tty=True)

    assert_exit(result, 0)


def test_ls_store_without_a_connection_fails_with_one(cli_json: CliHarness) -> None:
    result = cli_json.invoke("ls-store", connection=False)

    assert_exit(result, 1)
    assert result.stdout == ""


@pytest.mark.parametrize(
    ("encrypted", "key_mode", "label"),
    [
        (False, None, "plain"),
        (True, KeyMode.KEYFILE, "encrypted (keyfile)"),
        (True, KeyMode.PASSPHRASE, "encrypted (passphrase)"),
        (True, None, "encrypted (unknown)"),
    ],
)
def test_encryption_label_names_the_mode_or_unknown(
    key_mode: KeyMode | None, label: str, *, encrypted: bool
) -> None:
    info = StoreInfo(
        name="a",
        encrypted=encrypted,
        key_mode=key_mode,
        revision=1,
        created_at=_WHEN,
        updated_at=_WHEN,
    )

    assert encryption_label(info) == label
