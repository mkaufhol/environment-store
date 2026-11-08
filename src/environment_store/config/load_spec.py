"""Load specifications: the stores to load and their secrets, in `ENV_STORE_LOAD`.

A deployment that sets `ENV_STORE_CONNECTION` and `ENV_STORE_LOAD` needs nothing else: the
specification names the stores in load order and carries the key or passphrase of every
encrypted one. Its text is one line, `envstore-load-v1:` followed by the unpadded URL-safe
base64 form of a JSON object:

    {"stores": ["base", "app"], "keys": {"app": {"key": "envstore-key-v1:..."}}}

A passphrase is stored as `{"passphrase": "..."}`, character for character. The secrets are
typed, so nothing is stripped or guessed when they are read back. Decoding is strict and its
errors are never chained and never contain the value, because the value holds keys.
"""

import base64
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, NoReturn, Self

from environment_store.core.errors import (
    ConfigurationError,
    InvalidKeyFileError,
    ValidationError,
)
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.core.validation import validate_store_name
from environment_store.crypto.keyfile import format_key, parse_key

__all__ = [
    "ENV_LOAD",
    "LOAD_SPEC_PREFIX",
    "LoadSpec",
    "decode_load_spec",
    "load_spec_from_environment",
]

ENV_LOAD: Final = "ENV_STORE_LOAD"
"""The environment variable that holds a load specification."""

LOAD_SPEC_PREFIX: Final = "envstore-load-v1:"
"""First characters of every load specification; names the format version."""

_VERSIONED: Final = re.compile(r"envstore-load-v(?P<version>[0-9]+):")
_BASE64URL: Final = re.compile(r"[A-Za-z0-9_-]+")
# A base64 group of 4 characters holds 3 bytes; a lone character in the last group holds none.
_INCOMPLETE_GROUP: Final = 1
_FIELDS: Final = frozenset({"stores", "keys"})
_KEY: Final = "key"
_PASSPHRASE: Final = "passphrase"  # noqa: S105 - a field name, not a password
_PUBLIC_WHAT: Final = "the text"

type _Fail = Callable[[str], NoReturn]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadSpec:
    """The stores to load, in order, and the secret of every encrypted one.

    Attributes:
        stores: Store names in load order; repeats are kept.
        keys: Store name → key or passphrase; only for stores in `stores`.
    """

    stores: tuple[str, ...]
    keys: Mapping[str, Secret] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and freeze the specification.

        Raises:
            ValidationError: No stores, an invalid store name, a key for a store the
                specification does not load, or a key that is neither a `KeyMaterial` nor a
                `Passphrase`.
        """
        object.__setattr__(self, "stores", tuple(self.stores))
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))
        if not self.stores:
            message = "a load specification needs at least one store"
            raise ValidationError(message)
        for name in self.stores:
            validate_store_name(name)
        for name, secret in self.keys.items():
            if name not in self.stores:
                message = (
                    f"a load specification has a key for store {name!r}, which it does not load"
                )
                raise ValidationError(message)
            if not isinstance(secret, KeyMaterial | Passphrase):
                message = f"the key of store {name!r} must be a KeyMaterial or a Passphrase"
                raise ValidationError(message)

    def encode(self) -> str:
        """Return the one-line text form, for `ENV_STORE_LOAD`.

        Returns:
            `envstore-load-v1:` and the unpadded URL-safe base64 form of the JSON object; the
            same specification always gives the same text.
        """
        payload = {
            "stores": list(self.stores),
            "keys": {name: _secret_record(self.keys[name]) for name in sorted(self.keys)},
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return LOAD_SPEC_PREFIX + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, text: str) -> Self:
        """Read the text form back.

        Args:
            text: The text from `encode`; surrounding whitespace is ignored.

        Returns:
            The specification.

        Raises:
            ConfigurationError: The text is not a load specification; the message says why,
                never what the text holds.
        """
        stores, keys = _fields(text, what=_PUBLIC_WHAT)
        return cls(stores=stores, keys=keys)


def decode_load_spec(text: str, *, what: str) -> LoadSpec:
    """Read a load specification and name its source in errors.

    Args:
        text: The text form; surrounding whitespace is ignored.
        what: Names the source in messages, e.g. `ENV_STORE_LOAD`.

    Returns:
        The specification.

    Raises:
        ConfigurationError: The text is not a load specification; the message says why,
            never what the text holds.
    """
    stores, keys = _fields(text, what=what)
    return LoadSpec(stores=stores, keys=keys)


def load_spec_from_environment(environ: Mapping[str, str]) -> LoadSpec | None:
    """Return the load specification in `ENV_STORE_LOAD`, if it is set.

    Args:
        environ: The environment variables.

    Returns:
        The specification, or `None` when the variable is unset or empty (empty counts as
        unset, as for every settings variable).

    Raises:
        ConfigurationError: The value is not valid UTF-8 or not a load specification.
    """
    text = environ.get(ENV_LOAD)
    if not text:
        return None
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        message = f"{ENV_LOAD} is not valid UTF-8"
        # Not chained: the encode error holds the whole value.
        raise ConfigurationError(message) from None
    return decode_load_spec(text, what=ENV_LOAD)


def _secret_record(secret: Secret) -> dict[str, str]:
    if isinstance(secret, KeyMaterial):
        return {_KEY: format_key(secret).rstrip("\n")}
    return {_PASSPHRASE: secret.text}


def _fields(text: str, *, what: str) -> tuple[tuple[str, ...], dict[str, Secret]]:
    def fail(reason: str) -> NoReturn:
        message = f"{what} is not a valid load specification: {reason}"
        # Never chained: a JSON or base64 error holds the whole value, keys included.
        raise ConfigurationError(message) from None

    payload = _payload(text.strip(), fail)
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        fail("it must hold an object with 'stores' and 'keys' and nothing else")
    stores = payload["stores"]
    if not isinstance(stores, list) or not all(isinstance(name, str) for name in stores):
        fail("'stores' must be a list of store names")
    if not stores:
        fail("it must name at least one store")
    if not all(_is_store_name(name) for name in stores):
        fail("'stores' must be a list of store names")
    records = payload["keys"]
    if not isinstance(records, dict):
        fail("'keys' must map store names to secrets")
    for name in records:
        if name not in stores:
            # Only a valid store name is shown: anything else might be a misplaced secret.
            which = repr(name) if _is_store_name(name) else "a name"
            fail(f"it has a key for {which}, which it does not load")
    return tuple(stores), {name: _secret(name, record, fail) for name, record in records.items()}


def _is_store_name(name: str) -> bool:
    try:
        validate_store_name(name)
    except ValidationError:
        return False
    return True


def _payload(text: str, fail: _Fail) -> object:
    if not text.startswith(LOAD_SPEC_PREFIX):
        versioned = _VERSIONED.match(text)
        # Compared as text: a long run of digits must not reach int()'s length limit.
        if versioned is not None and versioned["version"].lstrip("0") not in {"", "1"}:
            fail("it was made by a newer version of environment-store: upgrade it")
        fail(f"it must start with {LOAD_SPEC_PREFIX!r}")
    body = text.removeprefix(LOAD_SPEC_PREFIX)
    if not body:
        fail(f"nothing follows {LOAD_SPEC_PREFIX!r}")
    if not _BASE64URL.fullmatch(body) or len(body) % 4 == _INCOMPLETE_GROUP:
        fail("the text after the prefix is not URL-safe base64 without padding")
    data = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    # Only the canonical form: unused bits of the last character must be zero.
    if base64.urlsafe_b64encode(data).decode("ascii").rstrip("=") != body:
        fail("the text after the prefix is not URL-safe base64 without padding")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except _RepeatedFieldError as error:
        known = error.name in _FIELDS | {_KEY, _PASSPHRASE} or _is_store_name(error.name)
        fail(f"it repeats {error.name!r}" if known else "it repeats a field")
    except (UnicodeDecodeError, ValueError, RecursionError):
        # RecursionError: deeply nested arrays exhaust the JSON decoder's recursion.
        fail("the text after the prefix is not UTF-8 JSON")


def _secret(name: str, record: object, fail: _Fail) -> Secret:
    if (
        not isinstance(record, dict)
        or len(record) != 1
        or not set(record) <= {_KEY, _PASSPHRASE}
        or not isinstance(next(iter(record.values())), str)
    ):
        fail(f'the secret of store {name!r} must be {{"key": ...}} or {{"passphrase": ...}}')
    kind, text = next(iter(record.items()))
    if kind == _KEY:
        try:
            return parse_key(text)
        except InvalidKeyFileError:
            fail(f"the key of store {name!r} is not valid key text")
    if not text:
        fail(f"the passphrase of store {name!r} is empty")
    try:
        return Passphrase(text=text)
    except ValidationError:
        fail(f"the passphrase of store {name!r} is not valid UTF-8")


class _RepeatedFieldError(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _unique_fields(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise _RepeatedFieldError(name)
        result[name] = value
    return result
