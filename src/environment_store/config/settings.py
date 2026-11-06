"""Settings resolution: CLI option > environment variable > project file > default (spec §5).

`resolve_settings` is the one place where the connection, the merge order, the project file's
store list and key paths come together, for the CLI, the TUI and the library one-liner alike.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from types import MappingProxyType
from typing import Final

from environment_store.config.project import (
    PROJECT_FILE_NAME,
    ProjectFile,
    find_project_file,
    read_project_file,
)
from environment_store.core.connection import connection_has_credentials
from environment_store.core.errors import ConfigurationError
from environment_store.core.merge import MergeOrder, order_from_setting, parse_bool_setting

__all__ = [
    "ENV_CONNECTION",
    "ENV_ORDERED_OVERWRITE",
    "ConnectionSource",
    "CredentialsInProjectFileWarning",
    "Settings",
    "missing_connection_message",
    "resolve_settings",
]

ENV_CONNECTION: Final = "ENV_STORE_CONNECTION"
"""The connection string variable (spec §5.1)."""

ENV_ORDERED_OVERWRITE: Final = "ENV_STORE_ORDERED_OVERWRITE"
"""The merge order variable (spec §5.2)."""


class ConnectionSource(StrEnum):
    """Where the connection string came from."""

    OPTION = auto()
    ENVIRONMENT = auto()
    PROJECT_FILE = auto()


class CredentialsInProjectFileWarning(UserWarning):
    """A project file problem the library one-liner reports, e.g. a password in `connection`."""


def missing_connection_message() -> str:
    """Return the D29 message: no connection is configured, and the three ways to set one."""
    return (
        "no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set "
        f"'connection' in {PROJECT_FILE_NAME}"
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    """The resolved configuration of one invocation.

    Attributes:
        connection: The connection string, or `None` if none is configured; may hold a
            password, so it stays out of the `repr`.
        connection_source: Where `connection` came from.
        ordered_overwrite: The merge order setting without `--first-wins` (env > file > true).
        stores: The project file's default store list.
        key_paths: The project file's `[keys]` (read-only).
        project_file: The project file that was read, or `None`.
        warnings: Messages for the user (password in the project file, ignored project file).
    """

    connection: str | None = field(repr=False)
    connection_source: ConnectionSource | None
    ordered_overwrite: bool
    stores: tuple[str, ...]
    key_paths: Mapping[str, Path]
    project_file: Path | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        """Freeze the collections."""
        object.__setattr__(self, "stores", tuple(self.stores))
        object.__setattr__(self, "key_paths", MappingProxyType(dict(self.key_paths)))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def require_connection(self) -> str:
        """Return the connection string.

        Returns:
            The connection string.

        Raises:
            ConfigurationError: None is configured (D29); the message names the three ways.
        """
        if self.connection is None:
            raise ConfigurationError(missing_connection_message())
        return self.connection

    def merge_order(self, *, first_wins: bool) -> MergeOrder:
        """Return the merge order; `--first-wins` beats every other setting (D14).

        Args:
            first_wins: Whether `--first-wins` was given.

        Returns:
            The merge order.
        """
        if first_wins:
            return MergeOrder.FIRST_WINS
        return order_from_setting(ordered_overwrite=self.ordered_overwrite)


def resolve_settings(  # noqa: PLR0913 - every input is a keyword-only boundary value
    *,
    connection: str | None,
    use_project: bool,
    environ: Mapping[str, str],
    cwd: Path,
    boundary: Path | None = None,
    uid: int | None = None,
) -> Settings:
    """Resolve the settings of one invocation.

    Empty environment variables count as unset (PD 8).

    Args:
        connection: The `-c` option, or `None`.
        use_project: `False` for `--no-project`: the project file is not even read.
        environ: The environment variables.
        cwd: Where the project file search starts.
        boundary: The last directory the search looks in; `None` for the filesystem root.
        uid: The user a project file must belong to (or root); `None` for the effective user.

    Returns:
        The settings.

    Raises:
        ConfigurationError: An empty `-c`, a broken project file or an invalid
            `ENV_STORE_ORDERED_OVERWRITE`.
    """
    if connection == "":
        message = "the connection option (-c/--connection) must not be empty"
        raise ConfigurationError(message)
    warnings: list[str] = []
    project = _project(cwd, boundary, uid, warnings) if use_project else None
    if (
        project is not None
        and project.connection is not None
        and connection_has_credentials(project.connection)
    ):
        warnings.append(_credentials_warning(project.path))
    resolved, source = _connection(connection, environ, project)
    return Settings(
        connection=resolved,
        connection_source=source,
        ordered_overwrite=_ordered_overwrite(environ, project),
        stores=() if project is None else project.stores,
        key_paths={} if project is None else project.keys,
        project_file=None if project is None else project.path,
        warnings=tuple(warnings),
    )


def _project(
    cwd: Path, boundary: Path | None, uid: int | None, warnings: list[str]
) -> ProjectFile | None:
    candidate = find_project_file(cwd, boundary=boundary, uid=uid)
    if candidate is None:
        return None
    if candidate.untrusted_reason is not None:
        # PD 32: an untrusted file contributes nothing but this warning.
        warnings.append(f"ignoring project file '{candidate.path}': {candidate.untrusted_reason}")
        return None
    return read_project_file(candidate.path)


def _credentials_warning(path: Path) -> str:
    return (
        f"the connection in project file '{path}' contains a password; credentials should not "
        f"be stored in a file that may be committed: set {ENV_CONNECTION} instead"
    )


def _connection(
    option: str | None, environ: Mapping[str, str], project: ProjectFile | None
) -> tuple[str | None, ConnectionSource | None]:
    if option is not None:
        return option, ConnectionSource.OPTION
    from_environment = environ.get(ENV_CONNECTION)
    if from_environment:
        return from_environment, ConnectionSource.ENVIRONMENT
    if project is not None and project.connection is not None:
        return project.connection, ConnectionSource.PROJECT_FILE
    return None, None


def _ordered_overwrite(environ: Mapping[str, str], project: ProjectFile | None) -> bool:
    raw = environ.get(ENV_ORDERED_OVERWRITE)
    if raw:
        return parse_bool_setting(raw, setting=ENV_ORDERED_OVERWRITE)
    if project is not None and project.ordered_overwrite is not None:
        return project.ordered_overwrite
    return True
