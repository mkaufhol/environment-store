from typing import cast

import pytest

from environment_store.core.errors import ValidationError
from environment_store.core.validation import (
    validate_store_name,
    validate_value,
    validate_variable_name,
    validate_variables,
)

# --- store names -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["a", "a9", "base_conf", "customer-a", "a1-b2_c3", "x" * 63, "a--b__c"]
)
def test_validate_store_name_accepts_lowercase_names_starting_with_a_letter(name: str) -> None:
    assert validate_store_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "A",
        "Base",
        "-a",
        "_a",
        "x" * 64,
        "../x",
        "a/b",
        "a\\b",
        "a.b",
        "a b",
        "a\n",
        "\na",
        "é",
        "a\x00",
    ],
)
def test_validate_store_name_rejects_bad_case_length_and_characters(name: str) -> None:
    with pytest.raises(ValidationError, match="invalid store name"):
        validate_store_name(name)


def test_validate_store_name_rejects_non_strings() -> None:
    with pytest.raises(ValidationError, match="store name must be a string"):
        validate_store_name(cast("str", b"base"))


def test_validate_store_name_error_names_the_rule() -> None:
    with pytest.raises(ValidationError, match=r"\^\[a-z\]\[a-z0-9_-\]\{0,62\}\$"):
        validate_store_name("Bad")


@pytest.mark.parametrize("name", ["9lives", "0abc", "0", "1-a", "2_b"])
def test_validate_store_name_rejects_names_starting_with_a_digit(name: str) -> None:
    # The nested prefix `STORE__VAR` must always be a valid shell variable name.
    with pytest.raises(ValidationError, match=r"starting with a letter \("):
        validate_store_name(name)


# --- variable names ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["A", "_", "_a", "DB_HOST", "db_host", "a1", "X" * 300])
def test_validate_variable_name_accepts_portable_posix_names(name: str) -> None:
    assert validate_variable_name(name) == name


@pytest.mark.parametrize("name", ["", "1A", "A-B", "A.B", "A B", "A=B", "Ä", "A\n", "A\x00", "$A"])
def test_validate_variable_name_rejects_non_portable_names(name: str) -> None:
    with pytest.raises(ValidationError, match="invalid variable name"):
        validate_variable_name(name)


def test_validate_variable_name_rejects_non_strings() -> None:
    with pytest.raises(ValidationError, match="variable name must be a string"):
        validate_variable_name(cast("str", 1))


def test_variable_names_are_case_sensitive() -> None:
    assert validate_variable_name("db_host") != validate_variable_name("DB_HOST")


# --- values ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",
        "plain",
        "multi\nline\r\nvalue\n",
        "-----BEGIN KEY-----\nabc\n-----END KEY-----",
        "  leading and trailing  ",
        "quotes ' \" `",
        "$HOME ${HOME} a=b",
        "unicode äöü ✓ 😀",
        "\t\x01\x7f",
    ],
)
def test_validate_value_accepts_any_string_without_nul(value: str) -> None:
    assert validate_value(value, variable="X") == value


def test_validate_value_rejects_nul_without_echoing_the_value() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_value("top-secret\x00", variable="API_KEY")

    message = str(excinfo.value)
    assert "API_KEY" in message
    assert "NUL" in message
    assert "top-secret" not in message


def test_validate_value_rejects_lone_surrogates_without_echoing_the_value() -> None:
    # A lone surrogate cannot be encoded as UTF-8, so it is not a UTF-8 string.
    with pytest.raises(ValidationError) as excinfo:
        validate_value("top-secret\ud800", variable="API_KEY")

    message = str(excinfo.value)
    assert "API_KEY" in message
    assert "UTF-8" in message
    assert "top-secret" not in message


def test_validate_value_rejects_non_strings_without_echoing_the_value() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_value(cast("str", 123456), variable="PORT")

    message = str(excinfo.value)
    assert "PORT" in message
    assert "must be a string" in message
    assert "123456" not in message


# --- variable maps -----------------------------------------------------------------------------


def test_validate_variables_returns_a_copy_of_a_valid_mapping() -> None:
    variables = {"DB_HOST": "localhost", "EMPTY": ""}

    result = validate_variables(variables)

    assert result == variables
    assert result is not variables


def test_validate_variables_accepts_an_empty_mapping() -> None:
    assert validate_variables({}) == {}


def test_validate_variables_rejects_an_invalid_name() -> None:
    with pytest.raises(ValidationError, match="invalid variable name 'BAD-NAME'"):
        validate_variables({"GOOD": "1", "BAD-NAME": "2"})


def test_validate_variables_rejects_an_invalid_value_without_echoing_it() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_variables({"TOKEN": "s3cr3t\x00"})

    assert "TOKEN" in str(excinfo.value)
    assert "s3cr3t" not in str(excinfo.value)
