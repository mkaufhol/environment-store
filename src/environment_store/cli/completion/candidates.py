"""What shell completion offers for parameter values.

- Store names, for the parameters that expect an existing store.
- Variable names of plaintext stores; an encrypted store offers none, because listing them
  needs its key, which completion never reads (no `ENV_STORE_KEY_<STORE>`, no `[keys]`, no
  prompt).
- Paths, as a marker that makes the shell complete files itself (`PathType`).

The backend is the one the command would use: `-c` from the line being completed,
`ENV_STORE_CONNECTION` or the project file, resolved by `resolve_settings` like for every
command. It is opened with `SetupMode.READ_ONLY`, so completion never creates or changes a file,
directory or schema. Any failure (no connection, a broken project file, a missing extra, an
unreachable server, a refused schema) completes nothing: completion must stay silent.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING, override

# Not type-only: typer evaluates the annotations of autocompletion callbacks at runtime.
import typer
from typer.core import CompletionItem
from typer.models import TyperPath

from environment_store.cli.runtime import Runtime
from environment_store.config.settings import Settings, resolve_settings
from environment_store.core.adapter import SetupMode
from environment_store.core.validation import STORE_NAME_PATTERN

if TYPE_CHECKING:
    # Type-only: the parameter type methods are typed with the vendored click classes.
    import os

    from typer._click import Context as ClickContext
    from typer._click import Parameter

__all__ = ["PathType", "ReadKeyType", "complete_stores", "complete_variables"]

_SEPARATOR = "="
_FILE = "file"
_STORE = "store"


class PathType(TyperPath):
    """A path parameter: completion lets the shell complete files.

    The value is passed on unchanged, as a string; the commands check it themselves (`-`
    for stdin or stdout, missing files), so nothing about their messages changes.
    """

    def __init__(self) -> None:
        """Accept any text, like a plain string parameter."""
        super().__init__(allow_dash=True)

    @override
    def convert(
        self,
        value: "str | os.PathLike[str]",
        param: "Parameter | None",
        ctx: "typer.Context | None",
    ) -> "str | bytes | os.PathLike[str]":
        """Return the value unchanged."""
        return value

    @override
    def shell_complete(
        self, ctx: "ClickContext", param: "Parameter", incomplete: str
    ) -> list[CompletionItem]:
        """Ask the shell for its own file completion of `incomplete`."""
        return [CompletionItem(incomplete, type=_FILE)]


class ReadKeyType(PathType):
    """`-k STORE=PATH` of the reading commands: the store part, then the path part."""

    @override
    def shell_complete(
        self, ctx: "ClickContext", param: "Parameter", incomplete: str
    ) -> list[CompletionItem]:
        """Offer `STORE=` for existing stores and the path itself; after `STORE=`, the path.

        With one store, `-k PATH` is enough, so the shell also completes the whole text
        as a path. The file item comes first: bash's script resets its reply on it, so there
        matching store names win and the files are the fallback.
        """
        name, separator, path = incomplete.partition(_SEPARATOR)
        if separator and STORE_NAME_PATTERN.fullmatch(name):
            return [CompletionItem(path, type=_FILE)]
        prefixed = (name + _SEPARATOR for name in _store_names(ctx))
        stores = [CompletionItem(value) for value in prefixed if value.startswith(incomplete)]
        return [CompletionItem(incomplete, type=_FILE), *stores]


def complete_stores(ctx: typer.Context, incomplete: str) -> list[str]:
    """The existing stores whose names start with `incomplete`.

    Args:
        ctx: The context of the command being completed.
        incomplete: The text typed so far.

    Returns:
        Matching store names, sorted; empty when the backend cannot be read.
    """
    return [name for name in _store_names(ctx) if name.startswith(incomplete)]


def complete_variables(ctx: typer.Context, incomplete: str) -> list[str]:
    """The variables of the plaintext stores in question that start with `incomplete`.

    The stores are `-s` for writing commands, which never use the project file's stores;
    otherwise the positional stores, else the project file's `stores` (`get KEY` comes before
    its stores). Encrypted stores offer nothing.

    Args:
        ctx: The context of the command being completed.
        incomplete: The text typed so far.

    Returns:
        Matching variable names, sorted and distinct; empty when nothing can be read.
    """
    names: set[str] = set()
    for record in _plain_records(ctx):
        names.update(name for name in record if name.startswith(incomplete))
    return sorted(names)


def _store_names(ctx: "ClickContext") -> list[str]:
    try:
        settings, runtime = _backend(ctx)
        if settings.connection is None:
            return []
        with runtime.adapter_opener(settings.connection, SetupMode.READ_ONLY) as adapter:
            return [info.name for info in adapter.list_stores()]
    # Completion never fails visibly; whatever went wrong, it offers nothing.
    except Exception:  # noqa: BLE001 - every error, also of a broken extra, means "no candidates"
        return []


def _plain_records(ctx: "ClickContext") -> list[Iterable[str]]:
    try:
        settings, runtime = _backend(ctx)
        stores = _stores_in_question(ctx, settings)
        if settings.connection is None or not stores:
            return []
        with runtime.adapter_opener(settings.connection, SetupMode.READ_ONLY) as adapter:
            records = [adapter.read_store(store) for store in stores]
    # Completion never fails visibly; whatever went wrong, it offers nothing.
    except Exception:  # noqa: BLE001 - every error, also of a broken extra, means "no candidates"
        return []
    # An encrypted record has no plaintext variables; its names would need the key.
    return [record.variables for record in records if record.variables is not None]


def _stores_in_question(ctx: "ClickContext", settings: Settings) -> tuple[str, ...]:
    if any(param.name == _STORE for param in ctx.command.params):
        # A writing command: only its `-s`, never the project file's stores.
        store = ctx.params.get(_STORE)
        return (store,) if isinstance(store, str) else ()
    stores = ctx.params.get("stores")
    if stores:
        return tuple(dict.fromkeys(stores))
    return settings.stores


def _backend(ctx: "ClickContext") -> tuple[Settings, Runtime]:
    # The root callback does not run while completing: the global options are the root
    # context's parsed parameters, and tests inject their Runtime as the context object.
    root = ctx.find_root()
    runtime = root.obj if isinstance(root.obj, Runtime) else Runtime()
    connection = root.params.get("connection")
    settings = resolve_settings(
        connection=connection if isinstance(connection, str) else None,
        use_project=not root.params.get("no_project"),
        environ=runtime.environ(),
        cwd=runtime.cwd(),
        boundary=runtime.project_boundary,
        uid=runtime.uid,
    )
    return settings, runtime
