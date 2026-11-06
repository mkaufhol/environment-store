"""SQLite connection strings: `sqlite:///relative.db` and `sqlite:////absolute.db` (spec §3)."""

import re
from pathlib import Path
from typing import Final

from environment_store.core.errors import ValidationError

__all__ = ["parse_sqlite_url"]

# Three slashes and a relative path, or four slashes and an absolute path. No host, query or
# fragment: SQLite has no server, and options in the string would be silently ignored.
_URL: Final[re.Pattern[str]] = re.compile(
    r"sqlite:///(?P<path>[^?#\x00]*[^/?#\x00])", re.IGNORECASE
)


def parse_sqlite_url(url: str) -> Path:
    """Return the database file a SQLite connection string names.

    Args:
        url: `sqlite:///relative/path.db` or `sqlite:////absolute/path.db`; the scheme is
            case-insensitive.

    Returns:
        The path as written: relative paths stay relative (to the working directory).

    Raises:
        ValidationError: The string is not a SQLite connection string with a file path.
    """
    match = _URL.fullmatch(url)
    if match is None:
        message = (
            "a SQLite connection string must name a database file: sqlite:///relative.db or "
            "sqlite:////absolute/path.db (no host, query or fragment)"
        )
        raise ValidationError(message)
    return Path(match.group("path"))
