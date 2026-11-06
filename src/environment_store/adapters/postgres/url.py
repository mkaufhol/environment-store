"""Parsing of PostgreSQL connection strings (spec §3.3.2, D13).

The `?schema=` parameter selects the dedicated schema and is removed before the string reaches
the driver; everything else is passed on unchanged. Pure and free of `psycopg`, so it is testable
without a server. Nothing here ever puts a password into a message or `repr`.
"""

import re
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote, urlsplit

from environment_store.core.errors import ValidationError

__all__ = ["DEFAULT_SCHEMA", "SCHEMA_PATTERN", "PostgresTarget", "parse_url"]

DEFAULT_SCHEMA: Final = "environment_store"
"""The schema used when the connection string has no `?schema=` (D13)."""

SCHEMA_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z_][a-z0-9_]{0,62}")
"""The schema name rule of spec §3.3.2; always applied with `fullmatch`."""

_SCHEME: Final[re.Pattern[str]] = re.compile(r"(postgresql|postgres)://", re.IGNORECASE)
_SCHEMA_PARAMETER: Final = "schema"
_CREDENTIAL_PARAMETER: Final = "password"
_REDACTED: Final = "***"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostgresTarget:
    """Where a PostgreSQL adapter connects to.

    Attributes:
        conninfo: The connection string for the driver, without `?schema=`; may hold a
            password, so it stays out of the `repr`.
        schema: The validated name of the dedicated schema.
        location: Schema and database for messages; never credentials.
        secrets: Every spelling of the password(s) in the connection string, for redaction.
    """

    conninfo: str = field(repr=False)
    schema: str
    location: str
    secrets: tuple[str, ...] = field(repr=False)

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
        ValidationError: Not a PostgreSQL URL, `schema` given twice, or a schema name that
            does not match `SCHEMA_PATTERN`. Messages never repeat the URL.
    """
    match = _SCHEME.match(url)
    if match is None:
        message = (
            "a PostgreSQL connection string must start with postgresql:// or postgres://, "
            "e.g. postgresql://user@host/db?schema=environment_store"
        )
        raise ValidationError(message)
    # libpq matches the scheme case-sensitively.
    url = match.group(1).lower() + url[len(match.group(1)) :]
    base, has_query, rest = url.partition("?")
    query, has_fragment, fragment = rest.partition("#")
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
    conninfo = base + ("?" + "&".join(kept) if has_query and kept else "")
    conninfo += "#" + fragment if has_fragment else ""
    return PostgresTarget(
        conninfo=conninfo,
        schema=schema,
        location=_location(base, schema),
        secrets=_secrets(base, kept),
    )


def _schema(values: list[str]) -> str:
    if not values:
        return DEFAULT_SCHEMA
    if len(values) > 1:
        message = "the schema parameter may be given only once"
        raise ValidationError(message)
    schema = values[0]
    if not SCHEMA_PATTERN.fullmatch(schema):
        message = (
            f"invalid PostgreSQL schema name {schema!r}: it must match "
            f"^{SCHEMA_PATTERN.pattern}$ (lowercase letters, digits, '_')"
        )
        raise ValidationError(message)
    return schema


def _location(base: str, schema: str) -> str:
    database = unquote(urlsplit(base).path.lstrip("/"))
    where = f"database {database!r}" if database else "the default database"
    return f"schema {schema!r} of {where}"


def _secrets(base: str, query_items: list[str]) -> tuple[str, ...]:
    raw: list[str] = []
    password = urlsplit(base).password
    if password:
        raw.append(password)
    for item in query_items:
        key, _, value = item.partition("=")
        if unquote(key) == _CREDENTIAL_PARAMETER and value:
            raw.append(value)
    found = {spelling for secret in raw for spelling in (secret, unquote(secret))}
    return tuple(sorted(found))
