import tomllib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.formats.toml_format import dumps, dumps_nested, loads
from tests.support.strategies import store_names, variable_maps


def test_dumps_writes_key_value_lines_in_input_order() -> None:
    assert dumps({"B": "2", "A": 'say "hi"'}) == 'B = "2"\nA = "say \\"hi\\""\n'


def test_dumps_of_nothing_is_empty() -> None:
    assert dumps({}) == ""


def test_dumps_nested_writes_one_table_per_store() -> None:
    output = dumps_nested({"base_conf": {"DB_HOST": "localhost"}, "customer-a": {"X": "1"}})

    assert output == '[base_conf]\nDB_HOST = "localhost"\n\n[customer-a]\nX = "1"\n'


def test_dumps_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'1A'"):
        dumps({"1A": "v"})


def test_dumps_refuses_nul_values_without_echoing_them() -> None:
    with pytest.raises(ValidationError, match="NUL") as excinfo:
        dumps({"A": "sec\x00ret"})

    assert "sec" not in str(excinfo.value)


def test_dumps_nested_refuses_invalid_store_names() -> None:
    with pytest.raises(ValidationError, match="store name"):
        dumps_nested({"a.b": {"A": "v"}})


def test_dumps_nested_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'A-B'"):
        dumps_nested({"base": {"A-B": "v"}})


def test_loads_reads_flat_string_values() -> None:
    text = 'A = "1"\nB = """\nmulti\nline"""\nC = \'lit\\eral\'\n'

    assert loads(text) == {"A": "1", "B": "multi\nline", "C": "lit\\eral"}


def test_loads_refuses_tables() -> None:
    with pytest.raises(ValidationError, match=r"nested.*'base'"):
        loads('[base]\nA = "1"\n')


@pytest.mark.parametrize(
    ("text", "type_name"),
    [
        ("A = 1", "int"),
        ("A = 1.5", "float"),
        ("A = true", "bool"),
        ('A = ["x"]', "list"),
        ("A = 1979-05-27T07:32:00Z", "datetime"),
    ],
)
def test_loads_refuses_values_that_are_not_strings(text: str, type_name: str) -> None:
    with pytest.raises(ValidationError, match=rf"'A'.*{type_name}"):
        loads(text)


@pytest.mark.parametrize("text", ["A = ", "A = 'x", 'A = "1"\nA = "2"', "= 1"])
def test_loads_refuses_malformed_toml(text: str) -> None:
    with pytest.raises(ValidationError, match="invalid TOML"):
        loads(text)


@pytest.mark.parametrize(
    "text", ["A = " + "[" * 100_000 + "]" * 100_000, "A = " + "{a=" * 5000 + "1" + "}" * 5000]
)
def test_loads_refuses_absurdly_deep_nesting(text: str) -> None:
    with pytest.raises(ValidationError, match="nested too deeply"):
        loads(text)


def test_loads_refuses_integers_beyond_the_conversion_limit() -> None:
    with pytest.raises(ValidationError, match="invalid TOML"):
        loads("A = 1" + "0" * 5000)


def test_loads_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'A-B'"):
        loads('A-B = "1"')


def test_loads_refuses_nul() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        loads('A = "x\\u0000"')


@given(variable_maps())
def test_loads_reads_back_what_dumps_writes(variables: dict[str, str]) -> None:
    assert loads(dumps(variables)) == variables


@given(st.dictionaries(store_names(), variable_maps(max_size=4), max_size=4))
def test_dumps_nested_round_trips_through_tomllib(stores: dict[str, dict[str, str]]) -> None:
    assert tomllib.loads(dumps_nested(stores)) == stores
