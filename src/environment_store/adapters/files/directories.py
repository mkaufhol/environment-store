"""Private store directories of the JSON and TOML adapters."""

from pathlib import Path
from typing import Final

__all__ = ["make_private_directory"]

_DIRECTORY_MODE: Final[int] = 0o700


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
