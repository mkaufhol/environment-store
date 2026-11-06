"""Cipher metadata of encrypted stores: cipher, key mode and Argon2id parameters.

Private module; the public import path is `environment_store.core.models`.
"""

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Final, Literal, Self, cast

from environment_store.core.errors import UnsupportedFormatError

__all__ = ["Cipher", "CipherMeta", "KdfParams", "KeyMode"]

_KDF_NAME: Final = "argon2id"
_SALT_LENGTH: Final[int] = 16
# Upper bounds stop a tampered store from forcing a huge Argon2id computation (D34).
_MAX_ITERATIONS: Final[int] = 10
_MAX_MEMORY_KIB: Final[int] = 1048576
_MAX_LANES: Final[int] = 16
# Argon2 needs at least 8 KiB of memory per lane.
_MIN_MEMORY_KIB_PER_LANE: Final[int] = 8


class Cipher(StrEnum):
    """Cipher of an encrypted store (D2)."""

    AES256GCM = "aes256gcm"


class KeyMode(StrEnum):
    """How the key of an encrypted store is supplied (D2)."""

    # auto() gives the lowercase member name: "keyfile", "passphrase".
    KEYFILE = auto()
    PASSPHRASE = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class KdfParams:
    """Argon2id parameters of a passphrase store (D34).

    Attributes:
        name: The KDF; only `argon2id`.
        iterations: Number of passes (`t`), 1 to 10.
        memory_kib: Memory in KiB (`m`), 8 per lane to 1 GiB.
        lanes: Degree of parallelism (`p`), 1 to 16.
        salt: Random 16-byte salt.
    """

    name: Literal["argon2id"] = _KDF_NAME
    iterations: int = 3
    memory_kib: int = 65536
    lanes: int = 4
    salt: bytes

    def __post_init__(self) -> None:
        """Validate the parameters.

        Raises:
            UnsupportedFormatError: Unknown KDF, non-integer or out-of-bounds values, or a salt
                that is not 16 bytes.
        """
        _check_kdf_name(self.name)
        _check_range(_kdf_int(self.lanes, "lanes"), "lanes", 1, _MAX_LANES)
        _check_range(_kdf_int(self.iterations, "iterations"), "iterations", 1, _MAX_ITERATIONS)
        _check_range(
            _kdf_int(self.memory_kib, "memory_kib"),
            "memory_kib",
            _MIN_MEMORY_KIB_PER_LANE * self.lanes,
            _MAX_MEMORY_KIB,
        )
        if not isinstance(self.salt, bytes) or len(self.salt) != _SALT_LENGTH:
            message = f"KDF salt must be {_SALT_LENGTH} bytes"
            raise UnsupportedFormatError(message)

    def to_json(self) -> dict[str, str | int]:
        """Return the stored form with the spec keys `name, t, m, p, salt` (salt base64).

        Returns:
            A JSON-compatible mapping.
        """
        return {
            "name": self.name,
            "t": self.iterations,
            "m": self.memory_kib,
            "p": self.lanes,
            "salt": base64.b64encode(self.salt).decode("ascii"),
        }

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Parse the stored form written by `to_json`.

        Args:
            data: Parsed JSON or TOML, untrusted.

        Returns:
            The validated parameters.

        Raises:
            UnsupportedFormatError: The document is not a valid KDF parameter object.
        """
        document = _json_object(
            data, what="KDF parameters", required=("name", "t", "m", "p", "salt")
        )
        _check_kdf_name(document["name"])
        return cls(
            iterations=_kdf_int(document["t"], "iterations"),
            memory_kib=_kdf_int(document["m"], "memory_kib"),
            lanes=_kdf_int(document["p"], "lanes"),
            salt=_decode_salt(document["salt"]),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CipherMeta:
    """Cipher metadata stored with an encrypted store and bound into its AAD (D5).

    Attributes:
        cipher: The cipher.
        mode: The key mode.
        kdf: KDF parameters; required for passphrase mode, absent for keyfile mode.
    """

    cipher: Cipher
    mode: KeyMode
    kdf: KdfParams | None = None

    def __post_init__(self) -> None:
        """Validate the metadata.

        Raises:
            UnsupportedFormatError: Wrong field types, or `kdf` not matching the mode.
        """
        if not isinstance(self.cipher, Cipher):
            message = "cipher must be a Cipher member"
            raise UnsupportedFormatError(message)
        if not isinstance(self.mode, KeyMode):
            message = "mode must be a KeyMode member"
            raise UnsupportedFormatError(message)
        if self.kdf is not None and not isinstance(self.kdf, KdfParams):
            message = "kdf must be KdfParams or None"
            raise UnsupportedFormatError(message)
        if self.mode is KeyMode.PASSPHRASE and self.kdf is None:
            message = "passphrase mode requires KDF parameters"
            raise UnsupportedFormatError(message)
        if self.mode is KeyMode.KEYFILE and self.kdf is not None:
            message = "keyfile mode takes no KDF parameters"
            raise UnsupportedFormatError(message)

    def to_json(self) -> dict[str, str | dict[str, str | int]]:
        """Return the stored form `{"cipher", "mode", "kdf"?}`.

        Returns:
            A JSON-compatible mapping; `kdf` only in passphrase mode.
        """
        document: dict[str, str | dict[str, str | int]] = {
            "cipher": self.cipher.value,
            "mode": self.mode.value,
        }
        if self.kdf is not None:
            document["kdf"] = self.kdf.to_json()
        return document

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Parse the stored form written by `to_json`.

        Args:
            data: Parsed JSON or TOML, untrusted.

        Returns:
            The validated metadata.

        Raises:
            UnsupportedFormatError: Unknown cipher, mode or KDF, or an invalid document.
        """
        document = _json_object(
            data, what="cipher metadata", required=("cipher", "mode"), optional=("kdf",)
        )
        return cls(
            cipher=_enum_member(Cipher, document["cipher"], what="cipher"),
            mode=_enum_member(KeyMode, document["mode"], what="key mode"),
            kdf=KdfParams.from_json(document["kdf"]) if "kdf" in document else None,
        )

    def to_file_table(self) -> dict[str, str | dict[str, str | int]]:
        """Return the `[cipher]` table of the file layout (spec §3.2): `{"name", "mode", "kdf"?}`.

        Same content as `to_json`, with the cipher under `name`; the AAD keeps using `to_json` (D5).

        Returns:
            A TOML-compatible mapping; `kdf` only in passphrase mode.
        """
        document = self.to_json()
        return {"name": document.pop("cipher"), **document}

    @classmethod
    def from_file_table(cls, data: object) -> Self:
        """Parse the `[cipher]` table written by `to_file_table`.

        Args:
            data: Parsed TOML or JSON, untrusted.

        Returns:
            The validated metadata.

        Raises:
            UnsupportedFormatError: Unknown cipher, mode or KDF, or an invalid table.
        """
        document = _json_object(
            data, what="cipher table", required=("name", "mode"), optional=("kdf",)
        )
        renamed = {("cipher" if key == "name" else key): value for key, value in document.items()}
        return cls.from_json(renamed)


# --- helpers -----------------------------------------------------------------------------------


def _check_kdf_name(name: object) -> None:
    if name != _KDF_NAME:
        message = f"unsupported KDF {name!r} (supported: {_KDF_NAME})"
        raise UnsupportedFormatError(message)


def _kdf_int(value: object, name: str) -> int:
    # bool is an int subclass, but `true` is not a valid parameter.
    if isinstance(value, bool) or not isinstance(value, int):
        message = f"KDF parameter {name} must be an integer"
        raise UnsupportedFormatError(message)
    return value


def _check_range(value: int, name: str, low: int, high: int) -> None:
    if not low <= value <= high:
        message = f"KDF parameter {name}={value} is out of bounds ({low} to {high})"
        raise UnsupportedFormatError(message)


def _decode_salt(value: object) -> bytes:
    message = "KDF salt must be a base64 string"
    if not isinstance(value, str):
        raise UnsupportedFormatError(message)
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as err:  # binascii.Error, or non-ASCII text
        raise UnsupportedFormatError(message) from err


def _json_object(
    data: object, *, what: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        message = f"{what} must be an object"
        raise UnsupportedFormatError(message)
    document = cast("Mapping[str, object]", data)
    keys = {str(key) for key in document}
    missing = sorted(set(required) - keys)
    if missing:
        message = f"{what} incomplete, missing: {', '.join(missing)}"
        raise UnsupportedFormatError(message)
    unknown = sorted(keys - set(required) - set(optional))
    if unknown:
        message = f"{what} not supported, unknown: {', '.join(unknown)}"
        raise UnsupportedFormatError(message)
    return document


def _enum_member[E: StrEnum](enum: type[E], value: object, *, what: str) -> E:
    supported = [member.value for member in enum]
    if isinstance(value, str) and value in supported:
        return enum(value)
    message = f"unsupported {what} {value!r} (supported: {', '.join(supported)})"
    raise UnsupportedFormatError(message)
