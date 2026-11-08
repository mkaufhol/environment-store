"""Settings resolution: CLI option > environment variable > project file > default.

`resolve_settings` is the one place where the connection, the merge order, the load
specification in `ENV_STORE_LOAD`, the project file's store list and key paths come together,
for the CLI, the TUI and the library one-liner alike.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from types import MappingProxyType
from typing import Final

from environment_store.config.load_spec import LoadSpec, load_spec_from_environment
from environment_store.config.project import (
    PROJECT_FILE_NAME,
    ProjectFile,
    check_key_paths,
    decode_project_file,
    find_project_file,
)
from environment_store.core.connection import connection_has_credentials
from environment_store.core.errors import ConfigurationError
from environment_store.core.merge import MergeOrder, order_from_setting, parse_bool_setting
from environment_store.core.validation import validate_store_name

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
"""The connection string variable."""

ENV_ORDERED_OVERWRITE: Final = "ENV_STORE_ORDERED_OVERWRITE"
"""The merge order variable."""


class ConnectionSource(StrEnum):
    """Where the connection string came from."""

    OPTION = auto()
    ENVIRONMENT = auto()
    PROJECT_FILE = auto()


class CredentialsInProjectFileWarning(UserWarning):
    """A project file problem the library one-liner reports, e.g. a password in `connection`."""


def missing_connection_message() -> str:
    """Return the message that no connection is configured, naming the three ways to set one.

    There is no default connection, so nothing is written to a location the user did not
    choose.
    """
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
        load_spec: The load specification in `ENV_STORE_LOAD`, or `None` if it is unset.
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
    load_spec: LoadSpec | None = None

    def __post_init__(self) -> None:
        """Freeze the collections and check the store names and key paths.

        Raises:
            ValidationError: An invalid store name or a relative key path.
        """
        object.__setattr__(self, "stores", tuple(self.stores))
        object.__setattr__(self, "key_paths", MappingProxyType(dict(self.key_paths)))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for store in self.stores:
            validate_store_name(store)
        check_key_paths(self.key_paths)

    @property
    def default_stores(self) -> tuple[str, ...]:
        """The stores to read when none are named: `ENV_STORE_LOAD`'s, else the project file's.

        Returns:
            The store names in load order; empty when neither gives any.
        """
        return self.stores if self.load_spec is None else self.load_spec.stores

    def require_connection(self) -> str:
        """Return the connection string.

        Returns:
            The connection string.

        Raises:
            ConfigurationError: None is configured; the message names the three ways.
        """
        if self.connection is None:
            raise ConfigurationError(missing_connection_message())
        return self.connection

    def merge_order(self, *, first_wins: bool) -> MergeOrder:
        """Return the merge order; `--first-wins` beats every other setting.

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

    Empty environment variables count as unset, for the `VAR= command` idiom.

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
        ConfigurationError: An empty `-c`, a broken project file, an invalid
            `ENV_STORE_ORDERED_OVERWRITE` or an invalid `ENV_STORE_LOAD`.
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
        load_spec=load_spec_from_environment(environ),
    )


def _project(
    cwd: Path, boundary: Path | None, uid: int | None, warnings: list[str]
) -> ProjectFile | None:
    candidate = find_project_file(cwd, boundary=boundary, uid=uid)
    if candidate is None:
        return None
    if candidate.untrusted_reason is not None:
        # An untrusted file contributes nothing but this warning.
        warnings.append(f"ignoring project file '{candidate.path}': {candidate.untrusted_reason}")
        return None
    # Parse the bytes the trust check saw, never the path a second time.
    return decode_project_file(candidate.content, path=candidate.path)


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
