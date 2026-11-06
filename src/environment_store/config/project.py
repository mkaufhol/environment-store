"""The project file `.envstore.toml`: discovery, trust check and strict parsing (spec §6.0.3).

Discovery walks from a start directory up to the filesystem root (or a boundary) and takes the
first regular file named `.envstore.toml`. A file owned by another user or writable by every
user, or a symbolic link owned by another user, is not trusted and is ignored (PD 32). The trust
check runs on the opened file and the bytes parsed are read from that same descriptor, so the
path cannot be swapped in between. Error messages name the file and the offending key, never a
value.
"""

import os
import re
import stat
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from environment_store.core.errors import ConfigurationError, ValidationError
from environment_store.core.validation import STORE_NAME_PATTERN, validate_store_name
from environment_store.crypto.keyfile import looks_like_key_file

__all__ = [
    "PROJECT_FILE_NAME",
    "ProjectFile",
    "ProjectFileCandidate",
    "anchor_connection",
    "check_key_paths",
    "decode_project_file",
    "find_project_file",
    "parse_project_file",
    "read_project_file",
    "untrusted_reason",
]

PROJECT_FILE_NAME: Final = ".envstore.toml"
"""Name of the project file (D17, D25)."""

_ALLOWED_KEYS: Final[tuple[str, ...]] = ("connection", "keys", "ordered_overwrite", "stores")
_ROOT_UID: Final = 0
# Opening a FIFO named like the project file must not block the search.
_OPEN_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
# `json://relative`, `toml://relative` (not `scheme:///absolute`, not `~`).
_RELATIVE_DIRECTORY: Final[re.Pattern[str]] = re.compile(
    r"(?P<scheme>json|toml)://(?P<path>[^/~].*)", re.IGNORECASE | re.DOTALL
)
# `sqlite:///relative` (not `sqlite:////absolute`, not `~`).
_RELATIVE_SQLITE: Final[re.Pattern[str]] = re.compile(
    r"(?P<scheme>sqlite):///(?P<path>[^/~].*)", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectFile:
    """The settings of a parsed project file.

    Attributes:
        path: The absolute path of the file.
        stores: Default store list for reading commands, in load order; `()` when absent.
        keys: Store name → absolute key file path (read-only).
        ordered_overwrite: Default merge order, or `None` when absent.
        connection: The connection string, anchored at the file's directory (PD 7), or `None`;
            it may hold a password, so it stays out of the `repr`.
    """

    path: Path
    stores: tuple[str, ...] = ()
    keys: Mapping[str, Path] = field(default_factory=dict)
    ordered_overwrite: bool | None = None
    connection: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Freeze the store list and the key table, and check them.

        Raises:
            ValidationError: A relative path, an invalid store name or a relative key path.
        """
        object.__setattr__(self, "stores", tuple(self.stores))
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))
        if not self.path.is_absolute():
            message = f"the project file path '{self.path}' must be absolute"
            raise ValidationError(message)
        for store in self.stores:
            validate_store_name(store)
        check_key_paths(self.keys)


def check_key_paths(keys: Mapping[str, Path]) -> None:
    """Check a key table: valid store names mapped to absolute paths.

    Args:
        keys: Store name → key file path.

    Raises:
        ValidationError: An invalid store name or a relative path.
    """
    for store, key_path in keys.items():
        validate_store_name(store)
        if not key_path.is_absolute():
            message = f"the key file path for store {store!r} must be absolute"
            raise ValidationError(message)


@dataclass(frozen=True, slots=True)
class ProjectFileCandidate:
    """The project file that discovery found.

    Attributes:
        path: The file.
        untrusted_reason: Why the file must be ignored (PD 32), or `None` if it is trusted.
        content: The bytes of a trusted file, read from the descriptor the trust check ran on;
            empty for an untrusted file.
    """

    path: Path
    untrusted_reason: str | None
    content: bytes = field(default=b"", repr=False, compare=False)


def untrusted_reason(st_uid: int, st_mode: int, uid: int) -> str | None:
    """Decide whether a project file may be used (PD 32).

    Group-writable files are allowed, because user-private groups make them common.

    Args:
        st_uid: The file owner.
        st_mode: The file mode.
        uid: The current (effective) user.

    Returns:
        `None` for a file owned by `uid` or root and not writable by every user, else the reason.
    """
    if st_uid not in (uid, _ROOT_UID):
        return "owned by another user"
    if st_mode & stat.S_IWOTH:
        return "writable by every user"
    return None


def find_project_file(
    start: Path, *, boundary: Path | None = None, uid: int | None = None
) -> ProjectFileCandidate | None:
    """Find the nearest project file from `start` upwards (spec §6.0.3).

    The first regular file found ends the search, trusted or not: an untrusted file is
    returned with its reason, so the caller can warn, and nothing above it is used.

    Args:
        start: The directory to start in, usually the working directory.
        boundary: The last directory to search; `None` searches up to the filesystem root.
        uid: The user that must own the file (or root); `None` means the effective user.

    Returns:
        The file found, or `None`; a trusted file comes with its content.

    Raises:
        ConfigurationError: A trusted file cannot be read.
    """
    directory = start.absolute()
    directories = [directory, *directory.parents]
    if boundary is not None and boundary.absolute() in directories:
        directories = directories[: directories.index(boundary.absolute()) + 1]
    for candidate_directory in directories:
        candidate = candidate_directory / PROJECT_FILE_NAME
        try:
            entry = candidate.lstat()
            status = candidate.stat() if stat.S_ISLNK(entry.st_mode) else entry
        except OSError:
            continue
        if stat.S_ISREG(status.st_mode):
            return _examine(candidate, entry, status, uid)
    return None


def _examine(
    path: Path, entry: os.stat_result, status: os.stat_result, uid: int | None
) -> ProjectFileCandidate:
    # A link owned by someone else may be retargeted at any time; never follow it.
    if stat.S_ISLNK(entry.st_mode) and _reason(entry, uid) == "owned by another user":
        return ProjectFileCandidate(path, "a symbolic link owned by another user")
    reason = _reason(status, uid)
    if reason is not None:
        return ProjectFileCandidate(path, reason)
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError as err:
        raise _read_error(path, err) from err
    try:
        # Decide again on what was opened: the path may have changed since the check.
        opened = os.fstat(fd)
        reason = _reason(opened, uid) if stat.S_ISREG(opened.st_mode) else "not a regular file"
        if reason is not None:
            return ProjectFileCandidate(path, reason)
        with os.fdopen(fd, "rb", closefd=False) as file:
            return ProjectFileCandidate(path, None, content=file.read())
    except OSError as err:
        raise _read_error(path, err) from err
    finally:
        os.close(fd)


def _read_error(path: Path, err: OSError) -> ConfigurationError:
    return ConfigurationError(f"cannot read project file '{path}': {err.strerror}")


def _reason(status: os.stat_result, uid: int | None) -> str | None:
    if sys.platform == "win32":
        return None  # No POSIX owner or mode bits to check.
    return untrusted_reason(status.st_uid, status.st_mode, os.geteuid() if uid is None else uid)


def read_project_file(path: Path) -> ProjectFile:
    """Read and parse a project file.

    Args:
        path: The file; a relative path is made absolute against the working directory.

    Returns:
        The parsed settings.

    Raises:
        ConfigurationError: The file cannot be read, is not UTF-8 or violates the schema.
    """
    path = path.absolute()
    try:
        data = path.read_bytes()
    except OSError as err:
        raise _read_error(path, err) from err
    return decode_project_file(data, path=path)


def decode_project_file(data: bytes, *, path: Path) -> ProjectFile:
    """Decode and parse the bytes of a project file, e.g. those read at discovery (PD 32).

    Args:
        data: The raw content.
        path: The file's absolute path.

    Returns:
        The parsed settings.

    Raises:
        ConfigurationError: The content is not UTF-8 or violates the schema.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        message = f"project file '{path}' is not valid UTF-8"
        # Not chained: the decode error holds the raw content.
        raise ConfigurationError(message) from None
    return parse_project_file(text, path=path)


def parse_project_file(text: str, *, path: Path) -> ProjectFile:
    """Parse the text of a project file against the strict schema (PD 6).

    Args:
        text: The TOML text.
        path: The file's absolute path; relative key and connection paths are anchored at its
            directory.

    Returns:
        The parsed settings.

    Raises:
        ConfigurationError: TOML syntax error, unknown key or a value of the wrong type; the
            message names the file and the key, never the value.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        message = f"project file '{path}' is not valid TOML"
        # Not chained: the parser error may quote the content.
        raise ConfigurationError(message) from None
    unknown = sorted(set(document) - set(_ALLOWED_KEYS))
    if unknown:
        message = (
            f"project file '{path}': unknown key '{unknown[0]}' "
            f"(allowed: {', '.join(_ALLOWED_KEYS)})"
        )
        raise ConfigurationError(message)
    connection = _connection(document.get("connection"), path)
    return ProjectFile(
        path=path,
        stores=_stores(document.get("stores", []), path),
        keys=_keys(document.get("keys", {}), path),
        ordered_overwrite=_ordered_overwrite(document.get("ordered_overwrite"), path),
        connection=None if connection is None else anchor_connection(connection, path.parent),
    )


def _error(path: Path, key: str, rule: str) -> ConfigurationError:
    return ConfigurationError(f"project file '{path}': {key} {rule}")


def _stores(value: object, path: Path) -> tuple[str, ...]:
    rule = (
        "must be a list of store names (lowercase letters, digits, '_', '-', "
        "starting with a letter)"
    )
    if not isinstance(value, list):
        raise _error(path, "'stores'", rule)
    for name in value:
        if not _is_store_name(name):
            raise _error(path, "'stores'", rule)
    return tuple(value)


def _keys(value: object, path: Path) -> dict[str, Path]:
    rule = "must map store names to key file paths"
    if not isinstance(value, dict):
        raise _error(path, "[keys]", rule)
    keys: dict[str, Path] = {}
    for store, raw in value.items():
        if not _is_store_name(store) or not isinstance(raw, str) or not raw or "\0" in raw:
            raise _error(path, "[keys]", rule)
        if looks_like_key_file(raw):
            raise _error(
                path,
                f"[keys] entry for store '{store}'",
                "holds key material: paths only, never key material",
            )
        keys[store] = _key_path(raw, path, store)
    return keys


def _key_path(raw: str, path: Path, store: str) -> Path:
    try:
        expanded = Path(raw).expanduser()
    except RuntimeError as err:
        message = (
            f"project file '{path}': [keys] entry for store '{store}' names an unknown "
            "home directory"
        )
        raise ConfigurationError(message) from err
    return path.parent / expanded


def _ordered_overwrite(value: object, path: Path) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise _error(path, "'ordered_overwrite'", "must be true or false")


def _connection(value: object, path: Path) -> str | None:
    if value is None or (isinstance(value, str) and value and "\0" not in value):
        return value
    raise _error(path, "'connection'", "must be a non-empty string without NUL characters")


def _is_store_name(value: object) -> bool:
    return isinstance(value, str) and STORE_NAME_PATTERN.fullmatch(value) is not None


def anchor_connection(url: str, base: Path) -> str:
    """Anchor relative file paths of a project file connection at its directory (PD 7).

    `json://`, `toml://` and `sqlite:///` paths that are relative become absolute below `base`,
    so the project file works from any subdirectory. Absolute paths, `~` paths and every other
    scheme are returned unchanged. Pure string handling.

    Args:
        url: The connection string from the project file.
        base: The project file's directory (absolute).

    Returns:
        The anchored connection string.
    """
    for pattern, separator in ((_RELATIVE_DIRECTORY, "://"), (_RELATIVE_SQLITE, ":///")):
        match = pattern.fullmatch(url)
        if match is not None:
            anchored = os.path.normpath(base / match.group("path"))
            return f"{match.group('scheme')}{separator}{anchored}"
    return url
