import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Final, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store._toml import TomlValue, dumps

type Typed = tuple[str, object]

_INT64_MIN: Final[int] = -(2**63)
_INT64_MAX: Final[int] = 2**63 - 1


def _typed(value: object) -> Typed:
    """Tag every value with its type, so that `True == 1` cannot hide a wrong round-trip."""
    if isinstance(value, Mapping):
        items = cast("Mapping[str, object]", value)
        return ("table", {key: _typed(item) for key, item in items.items()})
    if isinstance(value, datetime):
        return ("datetime", value.astimezone(UTC))
    return (type(value).__name__, value)


# --- strategies -------------------------------------------------------------------------------

_keys: st.SearchStrategy[str] = st.text(st.characters(exclude_categories=("Cs",)), max_size=12)
_strings: st.SearchStrategy[str] = st.text(st.characters(exclude_categories=("Cs",)))
_offsets: st.SearchStrategy[timezone] = st.integers(
    min_value=-23 * 60 - 59, max_value=23 * 60 + 59
).map(lambda minutes: timezone(timedelta(minutes=minutes)))
# One day of margin at both ends: offsets stay below 24 hours, so every instant has a UTC form.
_datetimes: st.SearchStrategy[datetime] = st.datetimes(
    min_value=datetime(1, 1, 2),  # noqa: DTZ001 - naive bounds are required by st.datetimes
    max_value=datetime(9999, 12, 30, 23, 59, 59, 999999),  # noqa: DTZ001
    timezones=st.one_of(st.just(UTC), _offsets),
)
_scalars: st.SearchStrategy[TomlValue] = st.one_of(
    _strings,
    st.integers(min_value=_INT64_MIN, max_value=_INT64_MAX),
    st.booleans(),
    _datetimes,
)
_values: st.SearchStrategy[TomlValue] = st.recursive(
    _scalars,
    lambda children: st.dictionaries(_keys, children, max_size=4),
    max_leaves=20,
)
_documents: st.SearchStrategy[dict[str, TomlValue]] = st.dictionaries(_keys, _values, max_size=6)


# --- property ---------------------------------------------------------------------------------


@given(_documents)
def test_dumps_round_trips_through_tomllib(document: dict[str, TomlValue]) -> None:
    assert _typed(tomllib.loads(dumps(document))) == _typed(document)


# --- layout -----------------------------------------------------------------------------------


def test_dumps_writes_the_spec_store_file_layout() -> None:
    document: dict[str, TomlValue] = {
        "format": 1,
        "encrypted": True,
        "revision": 7,
        "created_at": datetime(2026, 11, 6, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
        "payload": "bm9uY2U=",
        "cipher": {
            "name": "aes256gcm",
            "mode": "passphrase",
            "kdf": {"name": "argon2id", "t": 3, "m": 65536, "p": 4, "salt": "c2FsdA=="},
        },
    }

    assert dumps(document) == (
        "format = 1\n"
        "encrypted = true\n"
        "revision = 7\n"
        "created_at = 2026-11-06T10:00:00Z\n"
        "updated_at = 2026-11-06T12:30:00Z\n"
        'payload = "bm9uY2U="\n'
        "\n"
        "[cipher]\n"
        'name = "aes256gcm"\n'
        'mode = "passphrase"\n'
        'kdf = { name = "argon2id", t = 3, m = 65536, p = 4, salt = "c2FsdA==" }\n'
    )


def test_dumps_writes_scalars_before_tables_whatever_the_input_order() -> None:
    document: dict[str, TomlValue] = {"variables": {"A": "1"}, "format": 1}

    assert dumps(document) == 'format = 1\n\n[variables]\nA = "1"\n'


def test_dumps_separates_consecutive_tables_with_a_blank_line() -> None:
    document: dict[str, TomlValue] = {"a": {"x": 1}, "b": {"y": 2}}

    assert dumps(document) == "[a]\nx = 1\n\n[b]\ny = 2\n"


def test_dumps_of_an_empty_document_is_empty() -> None:
    assert dumps({}) == ""


def test_dumps_writes_empty_tables_as_headers_and_empty_inline_tables_as_braces() -> None:
    document: dict[str, TomlValue] = {"variables": {}, "cipher": {"kdf": {}}}

    assert dumps(document) == "[variables]\n\n[cipher]\nkdf = {}\n"


# --- keys -------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["DB_HOST", "a-b", "0", "_", "Z9"])
def test_dumps_writes_keys_matching_the_bare_key_pattern_unquoted(key: str) -> None:
    assert dumps({key: 1}) == f"{key} = 1\n"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("", '""'),
        ("a.b", '"a.b"'),
        ("a b", '"a b"'),
        ("ä", '"ä"'),
        ('a"b', '"a\\"b"'),
    ],
)
def test_dumps_quotes_keys_that_are_not_bare(key: str, expected: str) -> None:
    assert dumps({key: 1}) == f"{expected} = 1\n"


def test_dumps_quotes_table_header_keys_that_are_not_bare() -> None:
    assert dumps({"my table": {"k": 1}}) == '["my table"]\nk = 1\n'


# --- strings ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", '"plain"'),
        ("", '""'),
        ('say "hi"', '"say \\"hi\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("line\nbreak", '"line\\nbreak"'),
        ("\b\t\f\r", '"\\b\\t\\f\\r"'),
        ("\x00\x1f\x7f", '"\\u0000\\u001F\\u007F"'),
        ("ünïcødé ✓ $HOME 'q'", "\"ünïcødé ✓ $HOME 'q'\""),
    ],
)
def test_dumps_writes_strings_as_escaped_basic_strings(value: str, expected: str) -> None:
    assert dumps({"k": value}) == f"k = {expected}\n"


def test_dumps_rejects_strings_with_lone_surrogates() -> None:
    with pytest.raises(ValueError, match="surrogate"):
        dumps({"k": "\ud800"})


# --- integers and booleans --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (-5, "-5"), (_INT64_MAX, str(_INT64_MAX)), (_INT64_MIN, str(_INT64_MIN))],
)
def test_dumps_writes_integers_in_decimal(value: int, expected: str) -> None:
    assert dumps({"k": value}) == f"k = {expected}\n"


@pytest.mark.parametrize("value", [_INT64_MAX + 1, _INT64_MIN - 1])
def test_dumps_rejects_integers_outside_the_toml_64_bit_range(value: int) -> None:
    with pytest.raises(ValueError, match="64-bit"):
        dumps({"k": value})


@pytest.mark.parametrize(("value", "expected"), [(True, "true"), (False, "false")])
def test_dumps_writes_booleans_as_toml_booleans(*, value: bool, expected: str) -> None:
    assert dumps({"k": value}) == f"k = {expected}\n"


# --- datetimes --------------------------------------------------------------------------------


def test_dumps_writes_datetimes_in_utc_with_z_suffix() -> None:
    value = datetime(2026, 11, 6, 12, 30, tzinfo=timezone(timedelta(hours=2)))

    assert dumps({"k": value}) == "k = 2026-11-06T10:30:00Z\n"


def test_dumps_keeps_microseconds_of_datetimes() -> None:
    value = datetime(2026, 11, 6, 10, 0, 0, 123456, tzinfo=UTC)

    assert dumps({"k": value}) == "k = 2026-11-06T10:00:00.123456Z\n"


@pytest.mark.parametrize(
    "value",
    [
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        datetime(9999, 12, 31, 23, tzinfo=timezone(timedelta(hours=-2))),
    ],
)
def test_dumps_rejects_datetimes_without_a_utc_equivalent(value: datetime) -> None:
    with pytest.raises(ValueError, match="UTC") as excinfo:
        dumps({"k": value})

    assert isinstance(excinfo.value.__cause__, OverflowError)


def test_dumps_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 11, 6, 10, 0)  # noqa: DTZ001 - the naive datetime is the point of the test

    with pytest.raises(ValueError, match="timezone-aware"):
        dumps({"k": naive})


# --- unsupported types ------------------------------------------------------------------------


@pytest.mark.parametrize("value", [1.5, None, b"bytes", ["list"]])
def test_dumps_rejects_unsupported_value_types(value: object) -> None:
    document = cast("dict[str, TomlValue]", {"k": value})

    with pytest.raises(TypeError, match="unsupported TOML value type"):
        dumps(document)


def test_dumps_rejects_unsupported_value_types_inside_inline_tables() -> None:
    document = cast("dict[str, TomlValue]", {"t": {"inner": {"k": 1.5}}})

    with pytest.raises(TypeError, match="unsupported TOML value type"):
        dumps(document)
