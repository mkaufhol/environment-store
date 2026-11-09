"""An existing store's key from the environment: `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD`.

This serves deployments that hand secrets over as environment variables (e.g. Heroku,
Kubernetes). The environment sits between an explicit source and the project file's `[keys]` in
the key precedence; `SecretResolver` and `EnvironmentStore` both read it through this module. A
store's key comes from its key variable or from the load specification in `ENV_STORE_LOAD`;
both at once is an error, because it is unclear which one is meant. The environment is consulted
only for encrypted stores: a key for a plaintext store is ignored, because environments are
shared. Messages name the variable, never its value.
"""

from collections.abc import Collection, Iterable, Mapping
from typing import Final, Protocol

from environment_store.config.load_spec import ENV_LOAD, load_spec_from_environment
from environment_store.core.errors import (
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeySourceError,
    ValidationError,
)
from environment_store.core.models import KeyMode, StoreInfo
from environment_store.core.names import key_variable
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret

__all__ = [
    "StoreInspector",
    "check_key_variables",
    "check_not_empty",
    "environment_key",
    "environment_key_source",
    "has_environment_key",
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
    """Refuse secret text that is empty once one trailing newline is stripped.

    Args:
        text: The raw text.
        what: Names the source in the message.

    Returns:
        The text, unchanged.

    Raises:
        KeySourceError: The text is empty after stripping one trailing LF or CRLF.
    """
    # Exactly one trailing LF or CRLF is stripped, as passphrase_from_text does.
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
    """Refuse encrypted stores of one command that share a set key variable.

    `my-app` and `my_app` both map to `ENV_STORE_KEY_MY_APP`, so it is unclear which store a
    set variable is meant for. Only encrypted stores count: a plaintext store ignores the
    variable, so it cannot be what the variable is for. There is no problem either when
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
    """Return an existing store's secret from the environment, if it gives one.

    Args:
        inspector: Reads the store's metadata (only when the environment has a key for it).
        store: The store name.
        environ: The environment variables.

    Returns:
        The secret, or `None` when neither `ENV_STORE_KEY_<STORE>` nor `ENV_STORE_LOAD` has a
        key for the store, or the store is plaintext (a key for a plaintext store is ignored:
        environments are shared).

    Raises:
        StoreNotFoundError: The environment has a key and the store does not exist.
        ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
        ValidationError: Both variables have a key for the store.
        KeySourceError: The key variable is set but empty, or not valid UTF-8.
        InvalidKeyFileError: A `keyfile` store and the key variable is not key text.
        KeyModeMismatchError: The secret does not fit the store's key mode.
    """
    if not has_environment_key(store, environ) or not inspector.store_info(store).encrypted:
        return None
    return environment_key(inspector, store, environ)


def environment_key(
    inspector: StoreInspector, store: str, environ: Mapping[str, str]
) -> Secret | None:
    """Return an encrypted store's secret from the environment, if it gives one.

    Args:
        inspector: Interprets the key variable and reads the store's key mode.
        store: The store name; the caller has checked that it is encrypted.
        environ: The environment variables.

    Returns:
        The secret from `ENV_STORE_KEY_<STORE>` or from `ENV_STORE_LOAD`, or `None` when
        neither has one.

    Raises:
        ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
        ValidationError: Both variables have a key for the store; the message names them,
            never a value.
        KeySourceError: The key variable is set but empty, or not valid UTF-8.
        InvalidKeyFileError: A `keyfile` store and the key variable is not key text.
        KeyModeMismatchError: The secret does not fit the store's key mode.
    """
    variable = key_variable(store)
    text = environ.get(variable)
    spec = load_spec_from_environment(environ)
    from_spec = None if spec is None else spec.keys.get(store)
    if text is not None and from_spec is not None:
        message = (
            f"store {store!r} gets a key from both {variable} and {ENV_LOAD}, so it is unclear "
            "which one is meant: set only one of them"
        )
        raise ValidationError(message)
    if text is not None:
        return parse_key_variable(inspector, store, text)
    if from_spec is not None:
        return _fitting(inspector, store, from_spec)
    return None


def environment_key_source(store: str, environ: Mapping[str, str]) -> str | None:
    """Name the variable that gives a store's key, without reading the store.

    Args:
        store: The store name.
        environ: The environment variables.

    Returns:
        `ENV_STORE_KEY_<STORE>` when it is set, else `ENV_STORE_LOAD` when its load
        specification has a key for the store, else `None`. A plaintext store still ignores it.

    Raises:
        ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
    """
    variable = key_variable(store)
    if variable in environ:
        return variable
    spec = load_spec_from_environment(environ)
    if spec is not None and store in spec.keys:
        return ENV_LOAD
    return None


def has_environment_key(store: str, environ: Mapping[str, str]) -> bool:
    """Tell whether the environment has a key for a store, without reading the store.

    Args:
        store: The store name.
        environ: The environment variables.

    Returns:
        Whether `ENV_STORE_KEY_<STORE>` is set or `ENV_STORE_LOAD` has a key for the store.

    Raises:
        ConfigurationError: `ENV_STORE_LOAD` is set but not a load specification.
    """
    return environment_key_source(store, environ) is not None


def _fitting(inspector: StoreInspector, store: str, secret: Secret) -> Secret:
    # The specification's secrets are typed, so a wrong kind is caught before decryption.
    mode = inspector.store_info(store).key_mode
    if mode is KeyMode.PASSPHRASE and isinstance(secret, KeyMaterial):
        message = f"{ENV_LOAD} holds key text for store {store!r}, which uses a passphrase"
        raise KeyModeMismatchError(message)
    if mode is KeyMode.KEYFILE and isinstance(secret, Passphrase):
        message = f"{ENV_LOAD} holds a passphrase for store {store!r}, which uses a key file"
        raise KeyModeMismatchError(message)
    return secret


def parse_key_variable(inspector: StoreInspector, store: str, text: str) -> Secret:
    """Interpret the value of an encrypted store's key variable.

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
