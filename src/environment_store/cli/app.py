"""The `envs` app: global options, the root callback and the registration of every command.

Importing this module needs the `cli` extra; without typer it raises `MissingExtraError`.
"""

from typing import Annotated, Final

from environment_store.core.errors import MissingExtraError

try:
    import typer
except ImportError as missing:
    extra = "cli"
    raise MissingExtraError(extra) from missing

from importlib.metadata import version

from environment_store.cli import encryption, exporting, migrate, stores, tui_command, variables
from environment_store.cli._typer import EnvsGroup
from environment_store.cli.completion import command as completion_command
from environment_store.cli.output import out
from environment_store.cli.runtime import Runtime
from environment_store.cli.state import CliState

__all__ = ["app", "build_app"]

_DISTRIBUTION: Final = "environment-store"
_HELP: Final = (
    "Keep environment variables in named, optionally encrypted stores and load them anywhere.\n\n"
    "Stores and keys can be saved in a project file, .envstore.toml (stores, [keys], "
    "ordered_overwrite, connection), found in the current directory or its parents."
)
# -h is a shorthand for --help. Click passes help_option_names from the root context to
# every command's context, so setting them here covers `envs` and every command.
_CONTEXT_SETTINGS: Final = {"help_option_names": ["-h", "--help"]}


def _print_version(ctx: typer.Context, value: bool) -> None:  # noqa: FBT001 - typer's signature
    # While completing, click parses the line leniently and still runs eager callbacks;
    # completion prints nothing but its answer (like click's own --help and --version).
    if value and not ctx.resilient_parsing:
        out(f"{_DISTRIBUTION} {version(_DISTRIBUTION)}")
        raise typer.Exit


ConnectionOpt = Annotated[
    str | None,
    typer.Option(
        "-c",
        "--connection",
        metavar="URL",
        help="Connection string, e.g. sqlite:///envs.db or json://envs (overrides "
        "ENV_STORE_CONNECTION and 'connection' in .envstore.toml).",
        show_default=False,
    ),
]
NoProjectOpt = Annotated[
    bool, typer.Option("--no-project", help="Ignore the project file .envstore.toml.")
]
NoInputOpt = Annotated[
    bool,
    typer.Option(
        "--noinput",
        help="Never prompt, even on a terminal: missing keys fail with exit code 4, missing "
        "confirmations (no -y) with exit code 1.",
    ),
]
VersionOpt = Annotated[
    bool,
    typer.Option(
        "--version",
        callback=_print_version,
        is_eager=True,
        expose_value=False,
        help="Print the version and exit.",
    ),
]


def _root(
    ctx: typer.Context,
    *,
    connection: ConnectionOpt = None,
    no_project: NoProjectOpt = False,
    noinput: NoInputOpt = False,
    _version: VersionOpt = False,
) -> None:
    # Only builds the state; settings are resolved per command. Tests inject a
    # Runtime as the context object.
    runtime = ctx.obj if isinstance(ctx.obj, Runtime) else Runtime()
    ctx.obj = CliState(
        runtime=runtime,
        connection_option=connection,
        use_project=not no_project,
        noinput=noinput,
    )


def build_app() -> typer.Typer:
    """Create the `envs` app with every command registered.

    Returns:
        A new app; tests add their own commands to it.
    """
    app = typer.Typer(
        cls=EnvsGroup,
        name=_DISTRIBUTION,
        help=_HELP,
        pretty_exceptions_enable=False,
        rich_markup_mode=None,
        no_args_is_help=True,
        add_completion=False,
        context_settings=_CONTEXT_SETTINGS,
    )
    app.callback()(_root)
    migrate.register(app)
    stores.register(app)
    variables.register(app)
    exporting.register(app)
    encryption.register(app)
    tui_command.register(app)
    completion_command.register(app)
    return app


app: typer.Typer = build_app()
"""The app the entry points run."""
