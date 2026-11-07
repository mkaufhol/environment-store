import io
import json
import os
import stat
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import dotenv
import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.core.merge import MergeOrder
from environment_store.formats.infer import Format
from environment_store.library.environment import Environment
from tests.support.strategies import store_names, variable_maps

BASE: Final = ("base", {"HOST": "localhost", "PORT": "5432"})
STAGING: Final = ("staging", {"HOST": "staging.example", "DEBUG": "1"})


def _env(
    *stores: tuple[str, Mapping[str, str]], order: MergeOrder = MergeOrder.LAST_WINS
) -> Environment:
    return Environment(stores=stores, order=order)


STORE_A: Final = ("store-a", {"ENV": "development", "DEBUG": "True"})
STORE_B: Final = ("store-b", {"ENV": "staging", "DB_NAME": "test"})


def test_variables_last_wins_in_store_order_each_store_sorted() -> None:
    # D52: base's names first, then staging's new ones; HOST keeps its first position.
    assert list(_env(BASE, STAGING).variables().items()) == [
        ("HOST", "staging.example"),
        ("PORT", "5432"),
        ("DEBUG", "1"),
    ]


def test_variables_follow_the_d52_example() -> None:
    assert list(_env(STORE_A, STORE_B).variables().items()) == [
        ("DEBUG", "True"),
        ("ENV", "staging"),
        ("DB_NAME", "test"),
    ]


def test_variables_first_wins_keep_the_d52_order_and_the_first_value() -> None:
    assert list(_env(STORE_A, STORE_B, order=MergeOrder.FIRST_WINS).variables().items()) == [
        ("DEBUG", "True"),
        ("ENV", "development"),
        ("DB_NAME", "test"),
    ]


def test_variables_first_wins_keeps_the_first_value() -> None:
    assert _env(BASE, STAGING, order=MergeOrder.FIRST_WINS).variables()["HOST"] == "localhost"


def test_with_sources_names_the_winning_store_in_store_order() -> None:
    assert list(_env(BASE, STAGING).with_sources().items()) == [
        ("HOST", ("staging.example", "staging")),
        ("PORT", ("5432", "base")),
        ("DEBUG", ("1", "staging")),
    ]


def test_nested_flat_keys_follow_store_order_each_store_sorted() -> None:
    assert list(_env(STAGING, BASE).nested_flat()) == [
        "STAGING__DEBUG",
        "STAGING__HOST",
        "BASE__HOST",
        "BASE__PORT",
    ]


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("dotenv", "DEBUG=True\nENV=staging\nDB_NAME=test\n"),
        ("json", '{\n  "DEBUG": "True",\n  "ENV": "staging",\n  "DB_NAME": "test"\n}\n'),
        ("toml", 'DEBUG = "True"\nENV = "staging"\nDB_NAME = "test"\n'),
    ],
)
def test_dumps_keeps_the_d52_order_in_every_format(fmt: str, expected: str) -> None:
    assert _env(STORE_A, STORE_B).dumps(fmt) == expected


def test_apply_sets_the_variables_in_the_d52_order() -> None:
    environ: dict[str, str] = {}

    _env(STORE_A, STORE_B).apply(environ=environ)

    assert list(environ) == ["DEBUG", "ENV", "DB_NAME"]


def test_nested_keeps_store_order_and_sorts_variables() -> None:
    nested = _env(STAGING, BASE).nested()

    assert list(nested) == ["staging", "base"]
    assert list(nested["staging"]) == ["DEBUG", "HOST"]


def test_nested_refuses_a_store_listed_twice() -> None:
    with pytest.raises(ValidationError, match="more than once"):
        _env(BASE, BASE).nested()


def test_nested_flat_prefixes_variables_with_the_store_name() -> None:
    assert _env(("customer-a", {"B": "2", "A": "1"})).nested_flat() == {
        "CUSTOMER_A__A": "1",
        "CUSTOMER_A__B": "2",
    }


def test_nested_flat_collision_is_a_validation_error() -> None:
    with pytest.raises(ValidationError, match="CUSTOMER_A__X"):
        _env(("customer-a", {"X": "1"}), ("customer_a", {"X": "2"})).nested_flat()


def test_environment_is_immutable_and_copies_its_input() -> None:
    variables = {"A": "1"}
    environment = _env(("a", variables))
    variables["A"] = "changed"

    assert environment.variables() == {"A": "1"}
    assert isinstance(environment.stores[0][1], Mapping)
    assert not isinstance(environment.stores[0][1], dict)


def test_environment_validates_names_and_values() -> None:
    with pytest.raises(ValidationError):
        _env(("Bad Name", {}))
    with pytest.raises(ValidationError):
        _env(("a", {"A": "nul\x00"}))


def test_environment_repr_hides_values() -> None:
    assert "localhost" not in repr(_env(BASE))


def test_environment_refuses_an_unknown_order() -> None:
    with pytest.raises(ValidationError, match="order"):
        Environment(stores=(), order="sideways")  # ty: ignore[invalid-argument-type] - the point


# --- apply (PD 14) -----------------------------------------------------------------------------


def test_apply_sets_missing_variables_only_and_returns_them() -> None:
    environ = {"HOST": "already"}

    applied = _env(BASE).apply(environ=environ)

    assert applied == {"PORT": "5432"}
    assert environ == {"HOST": "already", "PORT": "5432"}


def test_apply_with_overwrite_replaces_existing_variables() -> None:
    environ = {"HOST": "already"}

    applied = _env(BASE).apply(overwrite=True, environ=environ)

    assert applied == {"HOST": "localhost", "PORT": "5432"}
    assert environ["HOST"] == "localhost"


def test_apply_nested_uses_prefixed_names() -> None:
    environ: dict[str, str] = {}

    _env(BASE).apply(nested=True, environ=environ)

    assert environ == {"BASE__HOST": "localhost", "BASE__PORT": "5432"}


def test_apply_defaults_to_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVSTORE_TEST_APPLY", raising=False)

    _env(("a", {"ENVSTORE_TEST_APPLY": "yes"})).apply()

    assert os.environ["ENVSTORE_TEST_APPLY"] == "yes"
    monkeypatch.delenv("ENVSTORE_TEST_APPLY")


# --- dumps -------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", [Format.DOTENV, "dotenv"])
def test_dumps_dotenv_writes_one_assignment_per_line(fmt: Format | str) -> None:
    assert _env(BASE).dumps(fmt) == "HOST=localhost\nPORT=5432\n"


def test_dumps_dotenv_nested_prefixes_names_with_the_store() -> None:
    assert _env(BASE).dumps(Format.DOTENV, nested=True) == (
        "BASE__HOST=localhost\nBASE__PORT=5432\n"
    )


def test_dumps_json_flat_and_nested() -> None:
    environment = _env(BASE, STAGING)

    assert json.loads(environment.dumps(Format.JSON)) == environment.variables()
    assert json.loads(environment.dumps(Format.JSON, nested=True)) == environment.nested()


def test_dumps_toml_flat_and_nested() -> None:
    environment = _env(BASE, STAGING)

    assert tomllib.loads(environment.dumps(Format.TOML)) == environment.variables()
    assert tomllib.loads(environment.dumps(Format.TOML, nested=True)) == environment.nested()


def test_dumps_refuses_an_unknown_format() -> None:
    with pytest.raises(ValidationError, match="dotenv, json, toml") as caught:
        _env(BASE).dumps("yaml")

    assert isinstance(caught.value.__cause__, ValueError)


# --- to_file -----------------------------------------------------------------------------------


def _dotenv_values(text: str) -> dict[str, str | None]:
    return dotenv.dotenv_values(stream=io.StringIO(text))


@pytest.mark.parametrize(
    ("name", "read"),
    [(".env", _dotenv_values), ("out.json", json.loads), ("out.toml", tomllib.loads)],
)
def test_to_file_infers_the_format_from_the_extension(
    tmp_path: Path, name: str, read: Callable[[str], object]
) -> None:
    path = tmp_path / name

    _env(BASE).to_file(path)

    assert read(path.read_text(encoding="utf-8")) == {"HOST": "localhost", "PORT": "5432"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_to_file_takes_a_string_path_and_an_explicit_format(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"

    _env(BASE).to_file(str(path), fmt="json")

    assert json.loads(path.read_text(encoding="utf-8")) == {"HOST": "localhost", "PORT": "5432"}


def test_to_file_without_inferable_format_asks_for_fmt(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"

    with pytest.raises(ValidationError, match="fmt"):
        _env(BASE).to_file(path)
    assert not path.exists()


def test_to_file_with_a_nul_character_in_the_path_is_a_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="NUL"):
        _env(BASE).to_file(tmp_path / "x\0.json")


def test_to_file_refuses_an_existing_file_unless_forced(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("old", encoding="utf-8")

    with pytest.raises(ValidationError, match="already exists"):
        _env(BASE).to_file(path)
    _env(BASE).to_file(path, force=True)

    assert path.read_text(encoding="utf-8") == "HOST=localhost\nPORT=5432\n"


def test_to_file_nested_writes_one_table_per_store(tmp_path: Path) -> None:
    path = tmp_path / "out.json"

    _env(BASE).to_file(path, nested=True)

    assert json.loads(path.read_text(encoding="utf-8")) == {"base": dict(BASE[1])}


def test_to_file_leaves_no_file_behind_for_a_refused_value(tmp_path: Path) -> None:
    path = tmp_path / ".env"

    with pytest.raises(ValidationError):
        _env(("a", {"A": "${HOME} and 'quotes'"})).to_file(path)
    assert not path.exists()


# --- round trips -------------------------------------------------------------------------------


@given(stores=st.lists(st.tuples(store_names(), variable_maps()), max_size=3))
def test_apply_round_trip_equals_variables(stores: list[tuple[str, dict[str, str]]]) -> None:
    environment = Environment(stores=tuple(stores), order=MergeOrder.LAST_WINS)
    environ: dict[str, str] = {}

    environment.apply(environ=environ)

    assert environ == environment.variables()


@given(stores=st.lists(st.tuples(store_names(), variable_maps()), max_size=3))
def test_json_file_round_trip_equals_variables(stores: list[tuple[str, dict[str, str]]]) -> None:
    environment = Environment(stores=tuple(stores), order=MergeOrder.FIRST_WINS)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "out.json"

        environment.to_file(path)

        assert json.loads(path.read_text(encoding="utf-8")) == environment.variables()
