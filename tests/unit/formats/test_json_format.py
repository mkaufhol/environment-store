import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.formats.json_format import dumps, dumps_nested, loads
from tests.support.strategies import store_names, variable_maps


def test_dumps_writes_an_indented_object_in_input_order_with_a_final_newline() -> None:
    assert dumps({"B": "2", "A": "ä"}) == '{\n  "B": "2",\n  "A": "ä"\n}\n'


def test_dumps_of_nothing_is_an_empty_object() -> None:
    assert dumps({}) == "{}\n"


def test_dumps_nested_puts_each_store_under_its_own_key() -> None:
    output = dumps_nested({"base_conf": {"DB_HOST": "localhost"}, "customer-a": {}})

    assert json.loads(output) == {"base_conf": {"DB_HOST": "localhost"}, "customer-a": {}}


def test_dumps_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'1A'"):
        dumps({"1A": "v"})


def test_dumps_refuses_nul_values_without_echoing_them() -> None:
    with pytest.raises(ValidationError, match="NUL") as excinfo:
        dumps({"A": "sec\x00ret"})

    assert "sec" not in str(excinfo.value)


def test_dumps_nested_refuses_invalid_store_names() -> None:
    with pytest.raises(ValidationError, match="store name"):
        dumps_nested({"Base": {"A": "v"}})


def test_dumps_nested_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'A-B'"):
        dumps_nested({"base": {"A-B": "v"}})


def test_loads_reads_a_flat_object_of_strings() -> None:
    assert loads('{"A": "1", "B": "multi\\nline"}') == {"A": "1", "B": "multi\nline"}


def test_loads_refuses_nested_objects() -> None:
    with pytest.raises(ValidationError, match=r"nested.*'base'"):
        loads('{"base": {"A": "1"}}')


@pytest.mark.parametrize(
    ("text", "type_name"),
    [
        ('{"A": 1}', "int"),
        ('{"A": 1.5}', "float"),
        ('{"A": true}', "bool"),
        ('{"A": null}', "NoneType"),
        ('{"A": ["x"]}', "list"),
        ('{"A": NaN}', "float"),
    ],
)
def test_loads_refuses_values_that_are_not_strings(text: str, type_name: str) -> None:
    with pytest.raises(ValidationError, match=rf"'A'.*{type_name}"):
        loads(text)


@pytest.mark.parametrize("text", ["[]", '"A"', "1", "null"])
def test_loads_refuses_documents_that_are_not_objects(text: str) -> None:
    with pytest.raises(ValidationError, match="flat object"):
        loads(text)


@pytest.mark.parametrize("text", ["", "{", '{"A": "1",}', "{'A': '1'}"])
def test_loads_refuses_malformed_json_with_its_position(text: str) -> None:
    with pytest.raises(ValidationError, match=r"invalid JSON.*line 1"):
        loads(text)


def test_loads_refuses_absurdly_deep_nesting() -> None:
    with pytest.raises(ValidationError, match="nested too deeply"):
        loads("[" * 1_000_000)


def test_loads_refuses_duplicate_keys() -> None:
    with pytest.raises(ValidationError, match=r"'A'.*more than once"):
        loads('{"A": "1", "A": "2"}')


def test_loads_refuses_invalid_variable_names() -> None:
    with pytest.raises(ValidationError, match="'A B'"):
        loads('{"A B": "1"}')


def test_loads_refuses_nul_and_lone_surrogates() -> None:
    with pytest.raises(ValidationError, match="NUL"):
        loads('{"A": "x\\u0000"}')
    with pytest.raises(ValidationError, match="surrogate"):
        loads('{"A": "x\\ud800"}')


@given(variable_maps())
def test_loads_reads_back_what_dumps_writes(variables: dict[str, str]) -> None:
    assert loads(dumps(variables)) == variables


@given(variable_maps())
def test_dumps_keeps_the_variable_order(variables: dict[str, str]) -> None:
    assert list(loads(dumps(variables))) == list(variables)


@given(st.dictionaries(store_names(), variable_maps(max_size=4), max_size=4))
def test_dumps_nested_round_trips_through_the_json_parser(
    stores: dict[str, dict[str, str]],
) -> None:
    assert json.loads(dumps_nested(stores)) == stores
