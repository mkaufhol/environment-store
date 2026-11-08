"""Opening the connection to a SQLite database file (D10, D43, D54).

A missing file is created, with its missing parent directories, only when asked to (the first
write); otherwise a missing file gives no connection and a read finds no stores. A read-only
connection never writes a byte, not even a lock, `-wal` or `-shm` file.
"""

import sqlite3
from pathlib import Path

from environment_store.adapters.sqlite.directories import (
    create_private_file,
    is_missing,
    make_private_directory,
)

__all__ = ["connect_file"]

# https://sqlite.org/fileformat2.html#the_database_header
_HEADER_SIZE = 100
_WRITE_VERSION = 18
_WAL_VERSION = 2


def connect_file(
    path: Path, *, create: bool, read_only: bool, busy_timeout: float
) -> sqlite3.Connection | None:
    """Connect to a database file in autocommit mode.

    Args:
        path: The absolute database path.
        create: Create a missing file and its missing directories first (D43).
        read_only: Open read-only (`SetupMode.READ_ONLY`, D54); ignored with `create`.
        busy_timeout: Seconds to wait for locks held by other connections.

    Returns:
        The connection, or `None` if the file is missing and `create` is false.

    Raises:
        sqlite3.Error: The file cannot be opened.
        OSError: A missing directory cannot be created, or the header of a file opened
            read-only cannot be read.
    """
    if create:
        make_private_directory(path.parent)
        create_private_file(path)
    elif is_missing(path):
        return None
    try:
        # check_same_thread=False: the adapter's lock, not the creating thread, guards the
        # connection.
        connection = sqlite3.connect(
            f"{path.as_uri()}?{_uri_parameters(path, create=create, read_only=read_only)}",
            timeout=busy_timeout,
            autocommit=True,
            check_same_thread=False,
            uri=True,
        )
    except sqlite3.OperationalError:
        if not create and is_missing(path):
            return None
        raise
    # Freed pages are zeroed: a deleted or replaced plaintext value leaves no trace.
    connection.execute("PRAGMA secure_delete = ON")
    # The driver's own UTF-8 decode error quotes the whole column (secret values); with
    # surrogateescape invalid bytes reach the codec, which reports them without a value.
    connection.text_factory = _decode_text
    return connection


def _uri_parameters(path: Path, *, create: bool, read_only: bool) -> str:
    if create:
        return "mode=rwc"
    if not read_only:
        # mode=rw: SQLite never creates the file itself (with its default mode, 0644) when it
        # is deleted between the existence check and the connect.
        return "mode=rw"
    # D54: an immutable file needs no lock, -wal or -shm file, and a WAL database without its
    # -wal file has no writer whose commits it could miss. A rollback-journal database (a file
    # system without WAL support keeps that mode) is changed in place by its writers, so only
    # the plain read-only mode, which honours their locks, can read it safely.
    wal = path.with_name(path.name + "-wal")
    if wal.exists() or not _is_wal_database(path):
        return "mode=ro"
    return "mode=ro&immutable=1"


def _is_wal_database(path: Path) -> bool:
    # The header's file format write version is 2 for WAL, 1 for a rollback journal; an empty
    # or short file has no header and no WAL either.
    with path.open("rb") as database:
        header = database.read(_HEADER_SIZE)
    return len(header) == _HEADER_SIZE and header[_WRITE_VERSION] == _WAL_VERSION


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="surrogateescape")
