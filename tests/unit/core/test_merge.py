from collections.abc import Mapping, Sequence

import pytest

from environment_store.core.errors import ConfigurationError, ValidationError
from environment_store.core.merge import (
    MergeOrder,
    merge,
    merge_with_sources,
    nested,
    nested_flat,
    nested_flat_key,
    order_from_setting,
    parse_bool_setting,
)

type Stores = Sequence[tuple[str, Mapping[str, str]]]

BASE: tuple[str, Mapping[str, str]] = ("base_conf", {"DB_HOST": "localhost", "DB_PORT": "5432"})
STAGING: tuple[str, Mapping[str, str]] = ("staging_env", {"DB_HOST": "10.0.0.5", "DEBUG": "1"})

# --- merge order (spec §2.2) -------------------------------------------------------------------


def test_merge_order_values_are_stable_strings() -> None:
    assert (MergeOrder.LAST_WINS.value, MergeOrder.FIRST_WINS.value) == ("last_wins", "first_wins")


def test_merge_without_stores_is_empty() -> None:
    assert merge([]) == {}


def test_merge_of_one_store_returns_its_variables() -> None:
    assert merge([BASE]) == {"DB_HOST": "localhost", "DB_PORT": "5432"}


def test_merge_defaults_to_last_wins() -> None:
    assert merge([BASE, STAGING])["DB_HOST"] == "10.0.0.5"


def test_merge_last_wins_takes_the_value_of_the_last_store_containing_the_variable() -> None:
    third: tuple[str, Mapping[str, str]] = ("customer_a", {"OTHER": "x"})

    assert merge([BASE, STAGING, third], order=MergeOrder.LAST_WINS)["DB_HOST"] == "10.0.0.5"


def test_merge_first_wins_does_not_overwrite_a_variable_already_set() -> None:
    assert merge([BASE, STAGING], order=MergeOrder.FIRST_WINS)["DB_HOST"] == "localhost"


@pytest.mark.parametrize("order", list(MergeOrder))
def test_merge_keeps_the_union_of_all_variables(order: MergeOrder) -> None:
    assert set(merge([BASE, STAGING], order=order)) == {"DB_HOST", "DB_PORT", "DEBUG"}


def test_merge_keeps_the_empty_string_as_a_value() -> None:
    stores: Stores = [("a", {"X": "set"}), ("b", {"X": ""})]

    assert merge(stores) == {"X": ""}


def test_merge_does_not_modify_its_input() -> None:
    first = {"X": "1"}
    merge([("a", first), ("b", {"X": "2", "Y": "3"})])

    assert first == {"X": "1"}


def test_merge_returns_a_new_dict_even_for_one_store() -> None:
    variables = {"X": "1"}
    result = merge([("a", variables)])
    result["X"] = "changed"

    assert variables == {"X": "1"}


def test_merge_treats_variable_names_case_sensitively() -> None:
    assert merge([("a", {"db_host": "x"}), ("b", {"DB_HOST": "y"})]) == {
        "db_host": "x",
        "DB_HOST": "y",
    }


# --- merge with sources (`ls --source`) ----------------------------------------------------------


def test_merge_with_sources_reports_the_winning_store_for_last_wins() -> None:
    assert merge_with_sources([BASE, STAGING]) == {
        "DB_HOST": ("10.0.0.5", "staging_env"),
        "DB_PORT": ("5432", "base_conf"),
        "DEBUG": ("1", "staging_env"),
    }


def test_merge_with_sources_reports_the_winning_store_for_first_wins() -> None:
    assert merge_with_sources([BASE, STAGING], order=MergeOrder.FIRST_WINS)["DB_HOST"] == (
        "localhost",
        "base_conf",
    )


@pytest.mark.parametrize("order", list(MergeOrder))
def test_merge_with_sources_values_match_merge(order: MergeOrder) -> None:
    sourced = merge_with_sources([BASE, STAGING], order=order)

    assert {name: value for name, (value, _) in sourced.items()} == merge(
        [BASE, STAGING], order=order
    )


# --- nested mode (§6.11) -----------------------------------------------------------------------


def test_nested_keeps_each_store_under_its_own_key() -> None:
    assert nested([BASE, STAGING]) == {
        "base_conf": {"DB_HOST": "localhost", "DB_PORT": "5432"},
        "staging_env": {"DB_HOST": "10.0.0.5", "DEBUG": "1"},
    }


def test_nested_keeps_the_load_order_of_the_stores() -> None:
    assert list(nested([STAGING, BASE])) == ["staging_env", "base_conf"]


def test_nested_copies_the_variables() -> None:
    variables = {"X": "1"}
    nested([("a", variables)])["a"]["X"] = "changed"

    assert variables == {"X": "1"}


def test_nested_rejects_a_store_listed_twice() -> None:
    with pytest.raises(ValidationError, match="store 'base_conf' is listed more than once"):
        nested([BASE, STAGING, BASE])


# --- nested flat keys (D30) --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("store", "variable", "expected"),
    [
        ("base_conf", "DB_HOST", "BASE_CONF__DB_HOST"),
        ("customer-a", "DB_HOST", "CUSTOMER_A__DB_HOST"),
        ("a", "db_host", "A__db_host"),
        ("x9", "_", "X9___"),
    ],
)
def test_nested_flat_key_joins_screaming_snake_store_and_unchanged_variable(
    store: str, variable: str, expected: str
) -> None:
    assert nested_flat_key(store, variable) == expected


def test_nested_flat_key_rejects_an_invalid_store_name() -> None:
    with pytest.raises(ValidationError, match="invalid store name"):
        nested_flat_key("Base", "X")


def test_nested_flat_key_rejects_an_invalid_variable_name() -> None:
    with pytest.raises(ValidationError, match="invalid variable name"):
        nested_flat_key("base", "1X")


def test_nested_flat_prefixes_every_variable_with_its_store() -> None:
    assert nested_flat([BASE, STAGING]) == {
        "BASE_CONF__DB_HOST": "localhost",
        "BASE_CONF__DB_PORT": "5432",
        "STAGING_ENV__DB_HOST": "10.0.0.5",
        "STAGING_ENV__DEBUG": "1",
    }


def test_nested_flat_reports_stores_that_map_to_the_same_prefix() -> None:
    stores: Stores = [("customer-a", {"X": "1"}), ("customer_a", {"X": "2"})]

    with pytest.raises(ValidationError, match="CUSTOMER_A__X") as excinfo:
        nested_flat(stores)

    assert "'customer-a'" in str(excinfo.value)
    assert "'customer_a'" in str(excinfo.value)


def test_nested_flat_reports_a_collision_through_a_double_underscore_variable() -> None:
    stores: Stores = [("a", {"B__C": "1"}), ("a__b", {"C": "2"})]

    with pytest.raises(ValidationError, match="A__B__C"):
        nested_flat(stores)


def test_nested_flat_collision_error_does_not_echo_values() -> None:
    stores: Stores = [("customer-a", {"X": "secret-one"}), ("customer_a", {"X": "secret-two"})]

    with pytest.raises(ValidationError) as excinfo:
        nested_flat(stores)

    assert "secret" not in str(excinfo.value)


def test_nested_flat_rejects_a_store_listed_twice() -> None:
    with pytest.raises(ValidationError, match="listed more than once"):
        nested_flat([BASE, BASE])


# --- bool settings (§5.2, D33) -----------------------------------------------------------------


@pytest.mark.parametrize("raw", ["true", "TRUE", "True", "1", "yes", "YES", "Yes"])
def test_parse_bool_setting_accepts_true_values_case_insensitively(raw: str) -> None:
    assert parse_bool_setting(raw, setting="ENV_STORE_ORDERED_OVERWRITE") is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "False", "0", "no", "NO", "No"])
def test_parse_bool_setting_accepts_false_values_case_insensitively(raw: str) -> None:
    assert parse_bool_setting(raw, setting="ENV_STORE_ORDERED_OVERWRITE") is False


@pytest.mark.parametrize("raw", ["", "on", "off", "y", "n", "2", "truthy", " true", "true\n"])
def test_parse_bool_setting_rejects_other_values(raw: str) -> None:
    with pytest.raises(ConfigurationError, match="ENV_STORE_ORDERED_OVERWRITE"):
        parse_bool_setting(raw, setting="ENV_STORE_ORDERED_OVERWRITE")


def test_parse_bool_setting_error_lists_the_accepted_values() -> None:
    with pytest.raises(ConfigurationError, match="true/false/1/0/yes/no"):
        parse_bool_setting("maybe", setting="ENV_STORE_ORDERED_OVERWRITE")


def test_order_from_setting_ordered_overwrite_means_last_wins() -> None:
    assert order_from_setting(ordered_overwrite=True) is MergeOrder.LAST_WINS


def test_order_from_setting_without_ordered_overwrite_means_first_wins() -> None:
    assert order_from_setting(ordered_overwrite=False) is MergeOrder.FIRST_WINS
