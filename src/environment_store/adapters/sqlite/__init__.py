"""SQLite adapter: one database file, schema created and upgraded automatically (D10-D13).

`open_sqlite` is the factory of the `sqlite` scheme (`sqlite:///relative.db`,
`sqlite:////absolute/path.db`). Imports `environment_store.core` and the shared SQL layer only.
"""

from environment_store.adapters.sqlite.adapter import (
    BUSY_TIMEOUT_SECONDS,
    SqliteAdapter,
    open_sqlite,
)
from environment_store.adapters.sqlite.url import parse_sqlite_url

__all__ = ["BUSY_TIMEOUT_SECONDS", "SqliteAdapter", "open_sqlite", "parse_sqlite_url"]
