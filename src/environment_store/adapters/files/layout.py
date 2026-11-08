"""The store file layout, independent of JSON or TOML.

```toml
format = 1
encrypted = true
revision = 7
created_at = 2026-11-06T10:00:00Z
updated_at = 2026-11-06T12:30:00Z
payload = "base64(nonce || ciphertext)"   # encrypted stores; plaintext ones have [variables]

[cipher]
name = "aes256gcm"
mode = "passphrase"
kdf = { name = "argon2id", t = 3, m = 65536, p = 4, salt = "base64…" }
```

The store name is the file name and is not repeated inside the file. Files are untrusted:
decoding validates everything, and errors name the file but never a value (it may be a secret).
"""

import base64
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Final, cast

from environment_store._toml import TomlValue
from environment_store.core.errors import BackendError, UnsupportedFormatError, ValidationError
from environment_store.core.models import CipherMeta, KeyMode, StoreInfo, StoreRecord

__all__ = ["FILE_FORMAT_VERSION", "document_to_info", "document_to_record", "record_to_document"]

FILE_FORMAT_VERSION: Final[int] = 1
"""Version of the store file layout, the `format` key."""

type TimestampParser = Callable[[object], datetime]

_HEADER: Final[tuple[str, ...]] = ("format", "encrypted", "revision", "created_at", "updated_at")
_PLAIN_KEYS: Final[frozenset[str]] = frozenset({*_HEADER, "variables"})
_SEALED_KEYS: Final[frozenset[str]] = frozenset({*_HEADER, "payload", "cipher"})


def record_to_document(record: StoreRecord) -> dict[str, TomlValue]:
    """Encode a record as a layout document.

    Args:
        record: The (valid) record.

    Returns:
        The document in the key order of the module docstring; variables sorted by name, so
        equal stores give equal files.
    """
    document: dict[str, TomlValue] = {
        "format": FILE_FORMAT_VERSION,
        "encrypted": record.encrypted,
        "revision": record.revision,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if record.variables is not None:
        document["variables"] = dict(sorted(record.variables.items()))
    else:
        # A sealed record always carries both (StoreRecord invariant).
        ciphertext = cast("bytes", record.ciphertext)
        meta = cast("CipherMeta", record.cipher_meta)
        document["payload"] = base64.b64encode(ciphertext).decode("ascii")
        document["cipher"] = meta.to_file_table()
    return document


def document_to_info(
    document: object, *, name: str, source: str, parse_timestamp: TimestampParser
) -> StoreInfo:
    """Decode the listing entry of a store file; never fails on unrecognised cipher metadata.

    Args:
        document: The parsed file, untrusted.
        name: The store name (the file stem).
        source: The file, for error messages.
        parse_timestamp: The serializer's timestamp decoder.

    Returns:
        The entry; `key_mode` is `None` for plaintext stores and unrecognised cipher metadata.

    Raises:
        UnsupportedFormatError: The file has another `format` version.
        BackendError: The header is corrupt.
    """
    header = _header(document, source=source)
    key_mode = _key_mode(header["cipher"]) if header["encrypted"] else None
    try:
        return StoreInfo(
            name=name,
            encrypted=cast("bool", header["encrypted"]),
            key_mode=key_mode,
            revision=cast("int", header["revision"]),
            created_at=_timestamp(header["created_at"], source=source, parse=parse_timestamp),
            updated_at=_timestamp(header["updated_at"], source=source, parse=parse_timestamp),
        )
    except ValidationError as err:
        # Includes timestamps without a UTC equivalent, e.g. 9999-12-31T23:59:59-01:00.
        raise _corrupt(source, str(err)) from err


def document_to_record(
    document: object, *, name: str, source: str, parse_timestamp: TimestampParser
) -> StoreRecord:
    """Decode and validate a complete store file.

    Args:
        document: The parsed file, untrusted.
        name: The store name (the file stem).
        source: The file, for error messages.
        parse_timestamp: The serializer's timestamp decoder.

    Returns:
        The record.

    Raises:
        UnsupportedFormatError: Another `format` version, or unrecognised cipher metadata.
        BackendError: Any other corruption.
    """
    info = document_to_info(document, name=name, source=source, parse_timestamp=parse_timestamp)
    header = cast("Mapping[str, object]", document)
    try:
        if not info.encrypted:
            variables = header["variables"]
            if not isinstance(variables, Mapping):
                raise _corrupt(source, "variables must be a table of strings")
            return StoreRecord.plain(
                name=name,
                variables=cast("Mapping[str, str]", variables),
                revision=info.revision,
                created_at=info.created_at,
                updated_at=info.updated_at,
            )
        return StoreRecord.sealed(
            name=name,
            ciphertext=_payload(header["payload"], source=source),
            cipher_meta=_cipher_meta(header["cipher"], source=source),
            revision=info.revision,
            created_at=info.created_at,
            updated_at=info.updated_at,
        )
    except ValidationError as err:
        raise _corrupt(source, str(err)) from err


# --- helpers -----------------------------------------------------------------------------------


def _corrupt(source: str, detail: str) -> BackendError:
    return BackendError(f"corrupt store file {source}: {detail}")


def _header(document: object, *, source: str) -> Mapping[str, object]:
    if not isinstance(document, Mapping) or "format" not in document:
        message = f"{source} is not an Environment Store file (no 'format' key)"
        raise BackendError(message)
    header = cast("Mapping[str, object]", document)
    version = header["format"]
    # type(...) is int: neither `true` nor `1.0` is format 1.
    if type(version) is not int or version != FILE_FORMAT_VERSION:
        message = (
            f"unsupported store file format in {source}: this version reads format "
            f"{FILE_FORMAT_VERSION}; upgrade Environment Store"
        )
        raise UnsupportedFormatError(message)
    encrypted = header.get("encrypted")
    if not isinstance(encrypted, bool):
        raise _corrupt(source, "'encrypted' must be true or false")
    expected = _SEALED_KEYS if encrypted else _PLAIN_KEYS
    keys = set(header)
    if keys != expected:
        missing = ", ".join(sorted(expected - keys)) or "none"
        unknown = ", ".join(sorted(str(key) for key in keys - expected)) or "none"
        raise _corrupt(source, f"wrong keys (missing: {missing}; unexpected: {unknown})")
    return header


def _timestamp(value: object, *, source: str, parse: TimestampParser) -> datetime:
    try:
        return parse(value)
    except ValueError as err:
        raise _corrupt(source, str(err)) from err


def _payload(value: object, *, source: str) -> bytes:
    if not isinstance(value, str):
        raise _corrupt(source, "payload must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as err:  # binascii.Error, or non-ASCII text
        raise _corrupt(source, "payload is not valid base64") from err


def _cipher_meta(value: object, *, source: str) -> CipherMeta:
    try:
        return CipherMeta.from_file_table(value)
    except UnsupportedFormatError as err:
        message = f"{source}: {err}"
        raise UnsupportedFormatError(message) from err


def _key_mode(value: object) -> KeyMode | None:
    try:
        return CipherMeta.from_file_table(value).mode
    except UnsupportedFormatError:
        return None
