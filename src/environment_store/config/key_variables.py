"""An existing store's key from `ENV_STORE_KEY_<STORE>` (spec §4.3, D53).

The variable sits between an explicit source and the project file's `[keys]` in D53's
precedence; `SecretResolver` and `EnvironmentStore` both read it through this module. It is
consulted only for encrypted stores: a variable for a plaintext store is ignored, because
environments are shared. Messages name the variable, never its value.
"""

from collections.abc import Collection, Iterable, Mapping
from typing import Final, Protocol

from environment_store.core.errors import (
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeySourceError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.names import key_variable
from environment_store.core.secrets import Secret

__all__ = [
    "StoreInspector",
    "check_key_variables",
    "check_not_empty",
    "parse_key_variable",
    "secret_from_environment",
]

_COLLISION: Final = 2
"""This many stores of one variable make it unclear which store it is for."""


class StoreInspector(Protocol):
    """What reading secrets needs to know about a store; implemented by `EnvironmentStore`."""

    def store_info(self, name: str, /) -> StoreInfo:
        """Return the listing entry of a store.

        Args:
            name: The store name.

        Returns:
            The entry; raises `StoreNotFoundError` for a missing store.
        """
        ...

    def parse_secret(self, name: str, text: str, /) -> Secret:
        """Interpret raw secret text by the store's key mode.

        Args:
            name: The store name.
            text: The raw text.

        Returns:
            The secret.
        """
        ...


def check_not_empty(text: str, *, what: str) -> str:
    """Refuse secret text that is empty after D3's newline stripping.

    Args:
        text: The raw text.
        what: Names the source in the message.

    Returns:
        The text, unchanged.

    Raises:
        KeySourceError: The text is empty after stripping one trailing LF or CRLF.
    """
    # Exactly one trailing LF or CRLF is stripped, as passphrase_from_text does (D3).
    stripped = text[:-2] if text.endswith("\r\n") else text.removesuffix("\n")
    if not stripped:
        message = f"{what} is empty"
        raise KeySourceError(message)
    return text


def check_key_variables(
    inspector: StoreInspector,
    stores: Iterable[str],
    *,
    explicit: Collection[str],
    environ: Mapping[str, str],
) -> None:
    """Refuse encrypted stores of one command that share a set key variable (D53).

    `my-app` and `my_app` both map to `ENV_STORE_KEY_MY_APP`, so it is unclear which store a
    set variable is meant for. Only encrypted stores count: a plaintext store ignores the
    variable (D53), so it cannot be what the variable is for. There is no problem either when
    the variable is not set, or when every such encrypted store has an explicit key.

    Args:
        inspector: Reads store metadata, only for stores that may collide.
        stores: The stores of the command (repeats allowed).
        explicit: The stores that have an explicit key (`-k`, `key=`, `keys=`, `Source`).
        environ: The environment variables.

    Raises:
        ValidationError: Two or more encrypted stores map to one set variable and not all of
            them have an explicit key; the message names them and the variable, never its value.
        StoreNotFoundError: A store that may collide does not exist.
    """
    by_variable: dict[str, list[str]] = {}
    for store in dict.fromkeys(stores):
        by_variable.setdefault(key_variable(store), []).append(store)
    for variable, names in by_variable.items():
        if len(names) < _COLLISION or variable not in environ or set(names) <= set(explicit):
            continue
        encrypted = [name for name in names if inspector.store_info(name).encrypted]
        if len(encrypted) >= _COLLISION and not set(encrypted) <= set(explicit):
            listed = ", ".join(repr(name) for name in encrypted)
            message = (
                f"encrypted stores {listed} all take their key from {variable}, so it is "
                "unclear which store it is for: unset it and give each of these stores its key "
                "explicitly"
            )
            raise ValidationError(message)


def secret_from_environment(
    inspector: StoreInspector, store: str, environ: Mapping[str, str]
) -> Secret | None:
    """Return an existing store's secret from `ENV_STORE_KEY_<STORE>`, if it gives one (D53).

    Args:
        inspector: Reads the store's metadata (only when the variable is set).
        store: The store name.
        environ: The environment variables.

    Returns:
        The secret, or `None` when the variable is not set or the store is plaintext (a
        variable for a plaintext store is ignored: environments are shared).

    Raises:
        StoreNotFoundError: The variable is set and the store does not exist.
        KeySourceError: The variable is set but empty, or not valid UTF-8.
        InvalidKeyFileError: A `keyfile` store and the value is not key text.
        KeyModeMismatchError: A `passphrase` store and the value is key text.
    """
    text = environ.get(key_variable(store))
    if text is None or not inspector.store_info(store).encrypted:
        return None
    return parse_key_variable(inspector, store, text)


def parse_key_variable(inspector: StoreInspector, store: str, text: str) -> Secret:
    """Interpret the value of an encrypted store's key variable (D53).

    Args:
        inspector: Interprets the text by the store's key mode.
        store: The store name; it must be encrypted.
        text: The value of `ENV_STORE_KEY_<STORE>`.

    Returns:
        The secret.

    Raises:
        KeySourceError: The value is empty or not valid UTF-8.
        InvalidKeyFileError: A `keyfile` store and the value is not key text.
        KeyModeMismatchError: A `passphrase` store and the value is key text.
    """
    variable = key_variable(store)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        message = f"{variable} is not valid UTF-8"
        # Not chained: the encode error holds the whole value.
        raise KeySourceError(message) from None
    check_not_empty(text, what=f"{variable}, the key or passphrase of store {store!r},")
    try:
        return inspector.parse_secret(store, text)
    except KeyModeMismatchError as error:
        # The parser speaks of a key file; here the key text came from the variable.
        message = f"{variable} holds key text, but store {store!r} uses a passphrase"
        raise KeyModeMismatchError(message, hint=error.hint) from error
    except InvalidKeyFileError as error:
        # The parser's message names neither the source nor the value; name the variable.
        message = f"{variable} does not hold a usable key for store {store!r}: {error.detail}"
        raise InvalidKeyFileError(message, hint=error.hint) from error
