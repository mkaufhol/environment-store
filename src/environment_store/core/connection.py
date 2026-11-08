"""Connection strings: the scheme registry and `open_adapter()`.

The registry names every adapter by import path, so the core never imports an adapter (or its
optional dependencies) until a connection string asks for it, and an adapter package never needs
to edit this file.
"""

import importlib
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol
from urllib.parse import unquote

from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.errors import MissingExtraError, ValidationError

__all__ = [
    "ADAPTER_FACTORIES",
    "CREDENTIAL_PARAMETERS",
    "AdapterEntry",
    "AdapterFactory",
    "connection_has_credentials",
    "connection_location",
    "open_adapter",
    "scheme_of",
]

CREDENTIAL_PARAMETERS: Final[frozenset[str]] = frozenset({"password", "sslpassword"})
"""Query parameters that hold secrets (libpq: the password and the client key's passphrase)."""

# RFC 3986 scheme characters, followed by "//".
_SCHEME: Final[re.Pattern[str]] = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://")
_IDENTIFIER: Final[str] = r"[A-Za-z_][A-Za-z0-9_]*"
_TARGET: Final[re.Pattern[str]] = re.compile(rf"{_IDENTIFIER}(?:\.{_IDENTIFIER})*:{_IDENTIFIER}")
# Like libpq: the user information ends at the first '@' that comes before any '/'.
_USERINFO: Final[re.Pattern[str]] = re.compile(r"([^@/]*)@")
# The port of one URI host entry: `h:5432`, `[::1]:5432`; never part of `[::1]`.
_HOST_PORT: Final[re.Pattern[str]] = re.compile(r":[^:\]]*$")
_DIRECTORY_SCHEMES: Final = frozenset({"json", "toml"})
_POSTGRES_SCHEMES: Final = frozenset({"postgresql", "postgres"})
# The PostgreSQL adapter's default schema; repeated here, as the core imports no adapter.
_DEFAULT_SCHEMA: Final = "environment_store"


class AdapterFactory(Protocol):
    """Opens an adapter for a connection string; every adapter package provides one."""

    def __call__(self, url: str, /, *, setup: SetupMode = SetupMode.AUTO) -> Adapter:
        """Parse `url` (scheme included) and open the adapter.

        Args:
            url: The complete connection string.
            setup: How to treat the database layout on open.

        Returns:
            The open adapter.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class AdapterEntry:
    """Where the factory of one scheme lives and which optional dependencies it needs.

    Attributes:
        target: `package.module:factory`, imported on first use.
        extra: The pip extra that installs `requires`, or `None` for core adapters.
        requires: Top-level packages whose absence means the extra is not installed.
    """

    target: str
    extra: str | None = None
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the entry and freeze `requires`.

        Raises:
            ValidationError: The target is not `module:attribute`, or packages are required
                without naming the extra that installs them.
        """
        if not _TARGET.fullmatch(self.target):
            message = f"adapter target {self.target!r} must have the form 'module:attribute'"
            raise ValidationError(message)
        object.__setattr__(self, "requires", tuple(self.requires))
        if self.requires and self.extra is None:
            message = f"adapter target {self.target!r} requires packages but names no extra"
            raise ValidationError(message)


_POSTGRES: Final[AdapterEntry] = AdapterEntry(
    target="environment_store.adapters.postgres:open_postgres",
    extra="postgres",
    requires=("psycopg",),
)

ADAPTER_FACTORIES: Final[Mapping[str, AdapterEntry]] = MappingProxyType(
    {
        "json": AdapterEntry(target="environment_store.adapters.files:open_json"),
        "toml": AdapterEntry(target="environment_store.adapters.files:open_toml"),
        "sqlite": AdapterEntry(target="environment_store.adapters.sqlite:open_sqlite"),
        "postgresql": _POSTGRES,
        "postgres": _POSTGRES,
    }
)
"""Every scheme (lowercase) and its factory; read-only."""


def scheme_of(url: str) -> str:
    """Return the scheme of a connection string.

    Args:
        url: A connection string such as `sqlite:///envs.db`.

    Returns:
        The scheme, lowercased.

    Raises:
        ValidationError: The string does not start with `scheme://`. The message never repeats
            the string, because it may hold credentials.
    """
    match = _SCHEME.match(url)
    if match is None:
        message = (
            "a connection string must start with 'scheme://', "
            "e.g. json://path/to/dir, sqlite:///envs.db or postgresql://host/db"
        )
        raise ValidationError(message)
    return match.group(1).lower()


def connection_has_credentials(url: str) -> bool:
    """Tell whether a connection string holds a password.

    The one detector shared by the warning about a password in a project file and the PostgreSQL
    adapter: a non-empty password in the URL user information, or a query parameter whose
    percent-decoded name is in `CREDENTIAL_PARAMETERS`.

    Args:
        url: The connection string; strings without `scheme://` never count as holding one.

    Returns:
        Whether the string contains credentials.
    """
    match = _SCHEME.match(url)
    if match is None:
        return False
    rest = url[match.end() :]
    userinfo = _USERINFO.match(rest)
    if userinfo is not None and userinfo.group(1).partition(":")[2]:
        return True
    query = rest.partition("?")[2].partition("#")[0]
    return any(
        unquote(item.partition("=")[0]) in CREDENTIAL_PARAMETERS for item in query.split("&")
    )


def open_adapter(
    url: str,
    *,
    setup: SetupMode = SetupMode.AUTO,
    factories: Mapping[str, AdapterEntry] = ADAPTER_FACTORIES,
) -> Adapter:
    """Open the adapter that a connection string selects.

    Args:
        url: The connection string; passed unchanged to the factory.
        setup: How to treat the database layout on open.
        factories: The scheme registry; tests pass their own.

    Returns:
        The open adapter.

    Raises:
        ValidationError: No scheme, or a scheme without an adapter.
        MissingExtraError: A package the adapter requires is not installed.
    """
    scheme = scheme_of(url)
    entry = factories.get(scheme)
    if entry is None:
        message = (
            f"unsupported connection scheme {scheme!r}: use one of {', '.join(sorted(factories))}"
        )
        raise ValidationError(message)
    return _load_factory(entry)(url, setup=setup)


def _load_factory(entry: AdapterEntry) -> AdapterFactory:
    module_name, _, attribute = entry.target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as err:
        # Only a missing optional dependency means "install the extra"; any other missing
        # module is a bug or a broken installation and must stay visible.
        missing = (err.name or "").partition(".")[0]
        if entry.extra is not None and missing in entry.requires:
            raise MissingExtraError(entry.extra) from err
        raise
    factory: AdapterFactory = getattr(module, attribute)
    return factory


def connection_location(url: str) -> str:
    """Describe where a connection string keeps its stores, for messages.

    Pure: nothing is opened or created. Paths are resolved like the file and SQLite adapters
    resolve them: relative to the working directory, with a leading `~` expanded.
    PostgreSQL locations name schema, database, host and port, never a user name or password.

    Args:
        url: A connection string the adapter accepted.

    Returns:
        The absolute store directory (`json://`, `toml://`), the absolute database file
        (`sqlite:///`), schema, database and host (`postgresql://`), or the scheme for any
        other backend.

    Raises:
        ValidationError: The string does not start with `scheme://`.
    """
    scheme = scheme_of(url)
    rest = url.partition("://")[2]
    if scheme in _DIRECTORY_SCHEMES:
        return str(_local_path(rest))
    if scheme == "sqlite":
        # sqlite:///relative.db and sqlite:////absolute.db: the third slash separates.
        return str(_local_path(rest.removeprefix("/")))
    if scheme in _POSTGRES_SCHEMES:
        return _postgres_location(rest)
    return f"the {scheme}:// backend"


def _local_path(raw: str) -> Path:
    path = Path(raw)
    # `~user` of an unknown user: the path stays as written, like any relative path.
    with suppress(RuntimeError):
        path = path.expanduser()
    return path.absolute()


def _with_port(host: str, port: str) -> str:
    # As in libpq: one port for every host, or one per host; a count libpq refuses is shown
    # as given.
    hosts = host.split(",")
    ports = port.split(",")
    if len(ports) == 1:
        ports *= len(hosts)
    if len(ports) != len(hosts):
        return f"{','.join(hosts)}:{port}"
    return ",".join(f"{entry}:{number}" for entry, number in zip(hosts, ports, strict=True))


def _postgres_location(rest: str) -> str:
    # Like libpq: the user information ends at the first '@' before any '/'; it is dropped.
    userinfo = _USERINFO.match(rest)
    if userinfo is not None:
        rest = rest[userinfo.end() :]
    hierarchy, _, query = rest.partition("?")
    host, _, database = hierarchy.partition("/")
    # Query parameters override the URI parts, as in libpq.
    given = {
        unquote(key): unquote(value)
        for key, _, value in (item.partition("=") for item in query.split("&"))
    }
    port = given.get("port")
    if "host" in given:
        host = given["host"]
    elif port is not None:
        # `port=` replaces the ports of the URI hosts, as in libpq.
        host = ",".join(_HOST_PORT.sub("", entry) for entry in unquote(host).split(","))
    else:
        host = unquote(host)
    database = given.get("dbname", unquote(database))
    schema = given.get("schema", _DEFAULT_SCHEMA)
    where = host if port is None else _with_port(host, port)
    database_text = f"database {database!r}" if database else "the default database"
    host_text = f"host {where!r}" if where else "the default host"
    return f"schema {schema!r} of {database_text} on {host_text}"
