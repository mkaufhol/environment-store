"""Bounded waits for `SetupMode.READ_ONLY` sessions on PostgreSQL.

Shell completion opens the backend read-only and must neither hang nor slow down every
keystroke, so every wait of such a session has an upper bound:

- Connecting: libpq applies `connect_timeout` to each host, so with several hosts no further
  host is tried once `READ_ONLY_CONNECT_TIMEOUT` is spent.
- Queries: `statement_timeout` and `lock_timeout`, so a lock held by a concurrent migration
  (ACCESS EXCLUSIVE) is not waited for until the migration ends.
- A network that stalls after connecting: TCP keepalives, so the socket fails instead of
  waiting for the system's TCP timeout (hours).

The connection's own settings for these are overridden, like the URL's `connect_timeout`.
"""

import time
from typing import Final

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_attempts, conninfo_to_dict, make_conninfo
from psycopg.rows import TupleRow

__all__ = ["READ_ONLY_CONNECT_TIMEOUT", "READ_ONLY_SESSION", "connect_read_only"]

READ_ONLY_CONNECT_TIMEOUT: Final = 2
"""Seconds a `SetupMode.READ_ONLY` adapter waits for the server; libpq's minimum."""

_LIMITS: Final[dict[str, int]] = {
    "connect_timeout": READ_ONLY_CONNECT_TIMEOUT,
    "keepalives": 1,
    "keepalives_idle": 1,
    "keepalives_interval": 1,
    "keepalives_count": 2,
}

READ_ONLY_SESSION: Final = (
    # The server refuses any write of this session too.
    sql.SQL("SET default_transaction_read_only = on"),
    sql.SQL(f"SET statement_timeout = '{READ_ONLY_CONNECT_TIMEOUT}s'"),
    sql.SQL(f"SET lock_timeout = '{READ_ONLY_CONNECT_TIMEOUT}s'"),
)
"""The plain SETs of a read-only session; they persist after the transaction that runs them."""


def connect_read_only(conninfo: str) -> psycopg.Connection[TupleRow]:
    """Connect in autocommit mode, trying the hosts in turn until the timeout is spent.

    Args:
        conninfo: The connection string for the driver.

    Returns:
        The connection, with the connect timeout and TCP keepalives of `_LIMITS`.

    Raises:
        psycopg.Error: No host could be resolved, or the host tried last refused or did not
            answer in time.
    """
    deadline = time.monotonic() + READ_ONLY_CONNECT_TIMEOUT
    # One attempt per host (and address), in the order and with the standby preference that
    # psycopg's own connect() would use.
    *first, last = conninfo_attempts(conninfo_to_dict(conninfo, **_LIMITS))
    for attempt in first:
        try:
            return psycopg.connect(make_conninfo("", **attempt), autocommit=True)
        except psycopg.Error:
            if time.monotonic() >= deadline:
                raise
    return psycopg.connect(make_conninfo("", **last), autocommit=True)
