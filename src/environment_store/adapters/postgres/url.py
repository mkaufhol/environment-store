"""Parsing of PostgreSQL connection strings (spec §3.3.2, D13).

The `?schema=` parameter selects the dedicated schema and is removed before the string reaches
the driver; everything else is passed on unchanged. The string is split the way libpq splits a
URI, so that the password found here is the one libpq uses: the user information ends at the
first '@' before any '/'. Strings that libpq would read differently than a person would (an
unencoded '@', '/' or '?' in the credentials, an unclosed '[') are rejected. Pure and free of
`psycopg`, so it is testable without a server. Nothing here ever puts a password into a message
or `repr`.
"""

import re
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote

from environment_store.core.errors import ValidationError

__all__ = ["DEFAULT_SCHEMA", "SCHEMA_PATTERN", "PostgresTarget", "parse_url"]

DEFAULT_SCHEMA: Final = "environment_store"
"""The schema used when the connection string has no `?schema=` (D13)."""

SCHEMA_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z_][a-z0-9_]{0,62}")
"""The schema name rule of spec §3.3.2; always applied with `fullmatch`."""

_SCHEME: Final[re.Pattern[str]] = re.compile(r"(postgresql|postgres)://", re.IGNORECASE)
# libpq ends the user information at the first '@' that comes before any '/'.
_USERINFO: Final[re.Pattern[str]] = re.compile(r"([^@/]*)@")
_COMPONENT_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[@:/,?&=]")
_SCHEMA_PARAMETER: Final = "schema"
# libpq parameters that hold secrets: the password and the passphrase of the client key.
_CREDENTIAL_PARAMETERS: Final[frozenset[str]] = frozenset({"password", "sslpassword"})
_DATABASE_PARAMETER: Final = "dbname"
_REDACTED: Final = "***"
_ENCODE_HINT: Final = (
    "invalid PostgreSQL connection string: percent-encode '@', '/' and '?' in the user name "
    "and password (as %40, %2F and %3F)"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresTarget:
    """Where a PostgreSQL adapter connects to.

    Attributes:
        conninfo: The connection string for the driver, without `?schema=`; may hold a
            password, so it stays out of the `repr`.
        schema: The validated name of the dedicated schema.
        location: Schema and database for messages; never credentials.
        secrets: Every spelling of the password(s) and client key passphrase(s) in the
            connection string, for redaction.
    """

    conninfo: str = field(repr=False)
    schema: str
    location: str
    secrets: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        """Check the schema name and the secrets.

        Raises:
            ValidationError: The schema name does not match `SCHEMA_PATTERN`, or `secrets` is
                not a tuple of strings.
        """
        _check_schema(self.schema)
        if not isinstance(self.secrets, tuple) or not all(
            isinstance(secret, str) for secret in self.secrets
        ):
            message = "the secrets of a PostgreSQL target must be a tuple of strings"
            raise ValidationError(message)

    def redact(self, text: str) -> str:
        """Replace every password occurrence in a (driver) message.

        Args:
            text: The text to clean.

        Returns:
            The text without any password.
        """
        # Longest first, so that a password containing another one is replaced as a whole.
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, _REDACTED)
        return text


def parse_url(url: str) -> PostgresTarget:
    """Split a `postgresql://` connection string into driver string and schema.

    Args:
        url: `postgresql://…` or `postgres://…`, optionally with `?schema=<name>`.

    Returns:
        The target.

    Raises:
        ValidationError: Not a PostgreSQL URL, a malformed one (NUL, not encodable as UTF-8,
            unencoded '@', '/' or '?' in the credentials, an unclosed '['), `schema` given
            twice, or a schema name that does not match `SCHEMA_PATTERN`. Messages never
            repeat the URL.
    """
    _check_text(url)
    match = _SCHEME.match(url)
    if match is None:
        message = (
            "a PostgreSQL connection string must start with postgresql:// or postgres://, "
            "e.g. postgresql://user@host/db?schema=environment_store"
        )
        raise ValidationError(message)
    # libpq matches the scheme case-sensitively.
    prefix = match.group(1).lower() + "://"
    rest = url[match.end() :]
    credentials = _USERINFO.match(rest)
    userinfo = None if credentials is None else credentials.group(1)
    if userinfo is not None and "?" in userinfo:
        raise ValidationError(_ENCODE_HINT)
    if userinfo is not None:
        prefix += userinfo + "@"
        rest = rest[len(userinfo) + 1 :]
    hierarchy, has_query, query = rest.partition("?")
    _check_hierarchy(hierarchy)
    kept: list[str] = []
    schemas: list[str] = []
    for item in filter(None, query.split("&")):
        key, _, value = item.partition("=")
        if unquote(key) == _SCHEMA_PARAMETER:
            schemas.append(unquote(value))
        else:
            # Kept byte for byte: '+' and escapes mean something else to libpq than to forms.
            kept.append(item)
    schema = _schema(schemas)
    conninfo = prefix + hierarchy + ("?" + "&".join(kept) if has_query and kept else "")
    return PostgresTarget(
        conninfo=conninfo,
        schema=schema,
        location=_location(hierarchy, kept, schema),
        secrets=_secrets(userinfo, kept),
    )


def _check_text(url: str) -> None:
    if "\x00" in url:
        message = "invalid PostgreSQL connection string: it contains a NUL character"
        raise ValidationError(message)
    # A lone surrogate (from undecodable bytes in the environment) cannot reach libpq.
    if not url.isascii() and _has_surrogate(url):
        message = "invalid PostgreSQL connection string: it is not valid Unicode text"
        raise ValidationError(message)
    _check_escapes(url)


def _check_escapes(url: str) -> None:
    # libpq decodes every component, and the driver needs each one to be UTF-8.
    for component in _COMPONENT_SEPARATORS.split(url):
        try:
            unquote(component, errors="strict")
        except UnicodeDecodeError:
            break
    else:
        return
    message = "invalid PostgreSQL connection string: a percent-escape does not encode UTF-8"
    raise ValidationError(message)


def _has_surrogate(text: str) -> bool:
    return any("\ud800" <= char <= "\udfff" for char in text)


def _check_hierarchy(hierarchy: str) -> None:
    # An '@' here means libpq read part of the credentials as host or database name.
    if "@" in hierarchy:
        raise ValidationError(_ENCODE_HINT)
    hosts = hierarchy.partition("/")[0]
    if any(host.startswith("[") and "]" not in host for host in hosts.split(",")):
        message = "invalid PostgreSQL connection string: an IPv6 host address lacks its ']'"
        raise ValidationError(message)


def _schema(values: list[str]) -> str:
    if not values:
        return DEFAULT_SCHEMA
    if len(values) > 1:
        message = "the schema parameter may be given only once"
        raise ValidationError(message)
    _check_schema(values[0])
    return values[0]


def _check_schema(schema: str) -> None:
    if not SCHEMA_PATTERN.fullmatch(schema):
        message = (
            f"invalid PostgreSQL schema name {schema!r}: it must match "
            f"^{SCHEMA_PATTERN.pattern}$ (lowercase letters, digits, '_')"
        )
        raise ValidationError(message)


def _location(hierarchy: str, query_items: list[str], schema: str) -> str:
    # Like libpq: the path names the database, a later dbname parameter overrides it.
    database = unquote(hierarchy.partition("/")[2])
    for item in query_items:
        key, _, value = item.partition("=")
        if unquote(key) == _DATABASE_PARAMETER:
            database = unquote(value)
    where = f"database {database!r}" if database else "the default database"
    return f"schema {schema!r} of {where}"


def _secrets(userinfo: str | None, query_items: list[str]) -> tuple[str, ...]:
    raw: list[str] = []
    if userinfo is not None:
        raw.append(userinfo.partition(":")[2])
    for item in query_items:
        key, _, value = item.partition("=")
        if unquote(key) in _CREDENTIAL_PARAMETERS:
            raw.append(value)
    found = {spelling for secret in raw for spelling in (secret, unquote(secret)) if spelling}
    return tuple(sorted(found))
