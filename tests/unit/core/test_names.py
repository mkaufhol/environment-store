"""Names derived from store names: SCREAMING_SNAKE_CASE and the key variable (D30, D40, D53)."""

import pytest
from hypothesis import given

from environment_store.core.names import (
    KEY_VARIABLE_PREFIX,
    is_key_variable,
    key_variable,
    screaming_snake,
)
from environment_store.core.validation import VARIABLE_NAME_PATTERN
from tests.support.strategies import store_names


@pytest.mark.parametrize(
    ("store", "expected"),
    [
        ("prod", "PROD"),
        ("customer-a", "CUSTOMER_A"),
        ("customer_a", "CUSTOMER_A"),
        ("a1-2_b", "A1_2_B"),
        ("x", "X"),
    ],
)
def test_screaming_snake_upper_cases_and_turns_dashes_into_underscores(
    store: str, expected: str
) -> None:
    assert screaming_snake(store) == expected


@pytest.mark.parametrize(
    ("store", "expected"),
    [
        ("prod", "ENV_STORE_KEY_PROD"),
        ("customer-a", "ENV_STORE_KEY_CUSTOMER_A"),
        ("my_app", "ENV_STORE_KEY_MY_APP"),
        ("s3-2fa", "ENV_STORE_KEY_S3_2FA"),
    ],
)
def test_key_variable_is_the_prefix_and_the_screaming_snake_name(store: str, expected: str) -> None:
    assert key_variable(store) == expected


def test_dash_and_underscore_spellings_share_one_variable() -> None:
    assert key_variable("my-app") == key_variable("my_app")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ENV_STORE_KEY_PROD", True),
        ("ENV_STORE_KEY_", True),
        ("ENV_STORE_CONNECTION", False),
        ("env_store_key_prod", False),
        ("XENV_STORE_KEY_PROD", False),
    ],
)
def test_is_key_variable_checks_the_prefix_case_sensitively(name: str, *, expected: bool) -> None:
    assert is_key_variable(name) is expected


def test_the_prefix() -> None:
    assert KEY_VARIABLE_PREFIX == "ENV_STORE_KEY_"


@given(store_names())
def test_every_valid_store_name_gives_a_valid_posix_variable_name(store: str) -> None:
    variable = key_variable(store)

    assert VARIABLE_NAME_PATTERN.fullmatch(variable)
    assert is_key_variable(variable)
