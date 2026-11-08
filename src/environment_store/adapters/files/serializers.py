"""The two file formats of the file adapters: JSON and TOML.

Both adapters share one implementation and differ only in the `FileSerializer` they use. A
serializer turns a layout document (see `layout`) into text and back, and knows how its format
stores timestamps: JSON as RFC 3339 strings, TOML as native offset date-times.
"""

import json
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from environment_store._toml import TomlValue, dumps

__all__ = ["JSON_SERIALIZER", "TOML_SERIALIZER", "FileSerializer"]


@dataclass(frozen=True, slots=True, kw_only=True)
class FileSerializer:
    """Text form of a store file.

    Attributes:
        name: Human-readable format name for messages, e.g. `JSON`.
        extension: File extension including the dot, e.g. `.json`.
        dumps: Serializes a document whose values are `str`, `int`, `bool`, aware `datetime`
            or mappings of those.
        loads: Parses text into an untrusted document; raises `ValueError` (or
            `RecursionError` for absurd nesting) on invalid text.
        parse_timestamp: Turns a parsed timestamp value into an aware `datetime`; raises
            `ValueError` for anything else.
    """

    name: str
    extension: str
    dumps: Callable[[Mapping[str, TomlValue]], str]
    loads: Callable[[str], object]
    parse_timestamp: Callable[[object], datetime]


def _timestamp_text(value: datetime) -> str:
    # The same form the TOML writer uses: UTC, "Z", microseconds only when present.
    return value.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"


def _jsonable(value: TomlValue) -> object:
    if isinstance(value, datetime):
        return _timestamp_text(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _json_dumps(document: Mapping[str, TomlValue]) -> str:
    # ensure_ascii=False keeps non-ASCII values readable; files are written as UTF-8.
    return json.dumps(_jsonable(document), indent=2, ensure_ascii=False) + "\n"


def _aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        message = "timestamp has no UTC offset"
        raise ValueError(message)
    return value


def _json_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        message = "timestamp must be an ISO 8601 string"
        raise ValueError(message)  # noqa: TRY004 - every malformed timestamp is a ValueError
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as err:
        message = "timestamp is not ISO 8601"
        raise ValueError(message) from err
    return _aware(parsed)


def _toml_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        message = "timestamp must be a TOML offset date-time"
        raise ValueError(message)  # noqa: TRY004 - every malformed timestamp is a ValueError
    return _aware(value)


JSON_SERIALIZER: Final[FileSerializer] = FileSerializer(
    name="JSON",
    extension=".json",
    dumps=_json_dumps,
    loads=json.loads,
    parse_timestamp=_json_timestamp,
)
"""`json://` store files."""

TOML_SERIALIZER: Final[FileSerializer] = FileSerializer(
    name="TOML",
    extension=".toml",
    dumps=dumps,
    loads=tomllib.loads,
    parse_timestamp=_toml_timestamp,
)
"""`toml://` store files: read with `tomllib`, written with the built-in writer.

The stdlib cannot write TOML, and `cryptography` stays the only required dependency.
"""
