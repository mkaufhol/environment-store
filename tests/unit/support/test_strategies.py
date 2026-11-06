from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from hypothesis import find, given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.core.models import CipherMeta, KdfParams, KeyMode, StoreRecord
from environment_store.core.validation import (
    validate_store_name,
    validate_value,
    validate_variable_name,
    validate_variables,
)
from tests.support.strategies import (
    cipher_metas,
    invalid_store_names,
    invalid_variable_names,
    kdf_params,
    plain_records,
    sealed_records,
    store_names,
    timestamps,
    values,
    variable_maps,
    variable_names,
)


def _reaches[T](strategy: st.SearchStrategy[T], condition: Callable[[T], bool]) -> bool:
    return condition(find(strategy, condition))


@given(store_names())
def test_store_names_are_valid(name: str) -> None:
    assert validate_store_name(name) == name


@given(store_names())
def test_store_names_start_with_a_letter(name: str) -> None:
    assert "a" <= name[0] <= "z"


@pytest.mark.parametrize("example", ["9lives", "0"])
def test_invalid_store_names_include_names_starting_with_a_digit(example: str) -> None:
    assert _reaches(invalid_store_names(), lambda name: name == example)


@given(invalid_store_names())
def test_invalid_store_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_store_name(name)


@pytest.mark.parametrize("example", ["", "../x", "a/b", "A", "x" * 64])
def test_invalid_store_names_include_the_dangerous_examples(example: str) -> None:
    assert _reaches(invalid_store_names(), lambda name: name == example)


@given(variable_names())
def test_variable_names_are_valid(name: str) -> None:
    assert validate_variable_name(name) == name


@given(invalid_variable_names())
def test_invalid_variable_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_variable_name(name)


@given(values())
def test_values_are_valid(value: str) -> None:
    assert validate_value(value, variable="X") == value


@pytest.mark.parametrize(
    "condition",
    [
        lambda value: value == "",
        lambda value: "\n" in value,
        lambda value: any(ord(char) > 0x7F for char in value),
        lambda value: '"' in value,
        lambda value: "'" in value,
        lambda value: "$" in value,
        lambda value: "=" in value,
        lambda value: value != value.strip() and value.strip() != "",
    ],
    ids=[
        "empty",
        "multi-line",
        "unicode",
        "double-quote",
        "single-quote",
        "dollar",
        "equals",
        "surrounding-whitespace",
    ],
)
def test_values_cover_the_tricky_cases(condition: Callable[[str], bool]) -> None:
    assert _reaches(values(), condition)


@given(variable_maps())
def test_variable_maps_are_valid(variables: dict[str, str]) -> None:
    assert validate_variables(variables) == variables


@given(timestamps())
def test_timestamps_are_aware_utc(timestamp: datetime) -> None:
    assert timestamp.tzinfo is UTC


def test_timestamps_include_microseconds() -> None:
    assert _reaches(timestamps(), lambda timestamp: timestamp.microsecond != 0)


@given(kdf_params())
def test_kdf_params_are_valid_and_round_trip(params: KdfParams) -> None:
    assert KdfParams.from_json(params.to_json()) == params


@given(cipher_metas())
def test_cipher_metas_round_trip(meta: CipherMeta) -> None:
    assert CipherMeta.from_json(meta.to_json()) == meta


@pytest.mark.parametrize("mode", list(KeyMode))
def test_cipher_metas_cover_every_key_mode(mode: KeyMode) -> None:
    assert _reaches(cipher_metas(), lambda meta: meta.mode is mode)


@given(plain_records())
def test_plain_records_are_unencrypted(record: StoreRecord) -> None:
    assert not record.encrypted
    assert record.created_at <= record.updated_at
    assert 1 <= record.revision <= 2**31 - 1


@given(sealed_records())
def test_sealed_records_are_encrypted(record: StoreRecord) -> None:
    assert record.encrypted
    assert record.info.key_mode is not None


@given(plain_records(revisions=st.just(1)), sealed_records(revisions=st.just(1)))
def test_records_accept_a_revision_strategy(plain: StoreRecord, sealed: StoreRecord) -> None:
    assert plain.revision == sealed.revision == 1
