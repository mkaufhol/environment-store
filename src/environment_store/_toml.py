"""Minimal TOML writer for the subset Environment Store writes.

The standard library can read TOML (`tomllib`) but not write it, and the core depends on
`cryptography` only, so the TOML file adapter and the TOML export format use this writer.

Supported values are `str`, `int`, `bool`, timezone-aware `datetime` and mappings of those.
Mappings at the top level become `[table]`s, deeper mappings inline tables. Datetimes are written
in UTC.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

__all__ = ["TomlScalar", "TomlValue", "dumps"]

type TomlScalar = str | int | bool | datetime
type TomlValue = TomlScalar | Mapping[str, TomlValue]

_BARE_KEY: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_-]+")
_INT64_MIN: Final[int] = -(2**63)
_INT64_MAX: Final[int] = 2**63 - 1
_FIRST_PRINTABLE: Final[int] = 0x20
_DELETE: Final[int] = 0x7F
_SURROGATES: Final[range] = range(0xD800, 0xE000)
_SHORT_ESCAPES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
        '"': '\\"',
        "\\": "\\\\",
    }
)


def dumps(document: Mapping[str, TomlValue]) -> str:
    """Serialize a document to TOML.

    Args:
        document: Top-level keys and values. Mapping values become `[table]` sections, written
            after all scalar values; mappings nested deeper become inline tables.

    Returns:
        The TOML text; every line ends with a newline. An empty document gives an empty string.

    Raises:
        TypeError: A value has a type outside the supported subset.
        ValueError: A value cannot be represented in TOML (naive datetime, datetime whose UTC
            equivalent falls outside years 1 to 9999, integer outside 64 bits, string with a lone
            surrogate).
    """
    scalars = [
        _key_value(key, value) for key, value in document.items() if not isinstance(value, Mapping)
    ]
    sections = ["".join(scalars)] if scalars else []
    sections.extend(
        _table(key, value) for key, value in document.items() if isinstance(value, Mapping)
    )
    return "\n".join(sections)


def _table(key: str, table: Mapping[str, TomlValue]) -> str:
    lines = [f"[{_key(key)}]\n"]
    lines.extend(_key_value(name, value) for name, value in table.items())
    return "".join(lines)


def _key_value(key: str, value: TomlValue) -> str:
    return f"{_key(key)} = {_value(value)}\n"


def _key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else _string(key)


def _value(value: TomlValue) -> str:
    # bool before int: bool is a subclass of int.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return _integer(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, datetime):
        return _datetime(value)
    if isinstance(value, Mapping):
        return _inline_table(value)
    message = f"unsupported TOML value type: {type(value).__name__}"
    raise TypeError(message)


def _integer(value: int) -> str:
    if not _INT64_MIN <= value <= _INT64_MAX:
        message = "TOML integers must fit into 64-bit signed range"
        raise ValueError(message)
    return str(value)


def _string(value: str) -> str:
    return '"' + "".join(_escape(char) for char in value) + '"'


def _escape(char: str) -> str:
    if char in _SHORT_ESCAPES:
        return _SHORT_ESCAPES[char]
    code = ord(char)
    if code < _FIRST_PRINTABLE or code == _DELETE:
        return f"\\u{code:04X}"
    if code in _SURROGATES:
        # Neither UTF-8 nor TOML escapes can carry a lone surrogate.
        message = "TOML strings cannot contain lone surrogate code points"
        raise ValueError(message)
    return char


def _datetime(value: datetime) -> str:
    if value.utcoffset() is None:
        message = "TOML datetimes must be timezone-aware"
        raise ValueError(message)
    # TOML offsets have minute precision only; UTC keeps the instant exact.
    try:
        utc = value.astimezone(UTC)
    except OverflowError as err:
        message = f"datetime {value.isoformat()} has no UTC equivalent within years 1 to 9999"
        raise ValueError(message) from err
    return utc.isoformat().removesuffix("+00:00") + "Z"


def _inline_table(table: Mapping[str, TomlValue]) -> str:
    if not table:
        return "{}"
    items = ", ".join(f"{_key(key)} = {_value(value)}" for key, value in table.items())
    return f"{{ {items} }}"
