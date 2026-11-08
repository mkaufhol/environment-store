"""Private directories and files for the SQLite database (D43, spec §3.2).

The same rule as `adapters.files.directories`; adapter subpackages do not import each other.
"""

import os
from pathlib import Path
from typing import Final

__all__ = ["create_private_file", "is_missing", "make_private_directory"]

_DIRECTORY_MODE: Final[int] = 0o700
_FILE_MODE: Final[int] = 0o600


def is_missing(path: Path) -> bool:
    """Tell whether a path does not exist.

    Only "does not exist" counts: other errors (no permission, a file as parent) are left to
    `sqlite3.connect` to report.

    Args:
        path: The path.

    Returns:
        Whether it is missing.
    """
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def create_private_file(path: Path) -> None:
    """Create a missing database file with mode 0600, like the file backend's store files.

    SQLite gives its -wal and -shm files the database file's mode, so they are private too.
    An existing file keeps its mode; a failure is left to `sqlite3.connect` to report.

    Args:
        path: The database file.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    except OSError:
        return
    os.close(fd)


def make_private_directory(directory: Path) -> None:
    """Create a missing directory and its missing parents with mode 0700.

    The mode is set explicitly, so it does not depend on the umask. Directories that exist
    already, also those created concurrently by another process, keep their mode.

    Args:
        directory: The directory to create.

    Raises:
        OSError: A directory cannot be created, e.g. because a path component is a file.
    """
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        current = current.parent
    for path in reversed(missing):
        try:
            path.mkdir(mode=_DIRECTORY_MODE)
        except FileExistsError:
            continue  # created concurrently: not ours to change
        # Before the next level is created: a umask like 0o277 would leave no write permission.
        path.chmod(_DIRECTORY_MODE)
