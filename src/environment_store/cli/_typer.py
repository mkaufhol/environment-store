"""The only touch points with typer internals: the group and command classes of `envs`.

- `EnvsGroup` maps every typer usage error (unknown command or option, missing argument, bad
  choice) to exit code 1 instead of click's 2, which means "not found" here, and every
  `EnvironmentStoreError` to `Error: <message>` on stderr (with the CLI's own hints) and
  its category's exit code.
- `EnvsCommand` resolves the settings before each command's callback, so a broken
  configuration fails every command. `invoke` runs only after the command's own arguments were
  parsed, so `envs <cmd> --help` never resolves settings. Every command is registered with
  `cls=EnvsCommand` (or a subclass). Its usage errors name a global option given after the
  command name, and say that writing commands never take their store (`-s`) from the project
  file.
- `OfflineCommand` resolves no settings: `keygen` reads neither the connection nor the project
  file, so a broken `.envstore.toml` cannot stop it.
- `EnvsGroup` also answers shell completion requests (`_<PROG>_COMPLETE` in the environment)
  through `completion.protocol`, silently; typer's own completion options stay off.
- `PassthroughCommand` splits the arguments at the first `--` before parsing; the tail is the
  command `run` executes, untouched.
"""

import os
import sys
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any, ClassVar, Final, cast, override

import typer
from typer.core import TyperCommand, TyperGroup, TyperOption

from environment_store.cli.completion.protocol import PASSTHROUGH, answer
from environment_store.cli.completion.protocol import complete_var as _complete_var
from environment_store.cli.errors import ExitCode, exit_code_for, message_for
from environment_store.cli.output import err, out
from environment_store.cli.state import get_state
from environment_store.core.errors import EnvironmentStoreError

if TYPE_CHECKING:
    # Type-only: typer's overridable methods are typed with the vendored click Context.
    from typer._click import Context as ClickContext

__all__ = [
    "EnvsCommand",
    "EnvsGroup",
    "OfflineCommand",
    "PassthroughCommand",
    "passthrough_args",
]

_SEPARATOR: Final = "--"
_PROGRAM: Final = "envs"
_STORE_PARAMETER: Final = "store"
_STORE_HINT: Final = (
    "writing commands never take the store from ENV_STORE_LOAD or the project file's 'stores'; "
    "name it with -s STORE"
)


class EnvsGroup(TyperGroup):
    """The root group: usage errors exit with 1, library errors with their category code."""

    @override
    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: "ClickContext | None" = None,
        **extra: object,
    ) -> "ClickContext":
        """Parse the global options; a usage error exits with 1."""
        try:
            return super().make_context(info_name, args, parent, **extra)
        except typer.TyperException as error:
            error.exit_code = ExitCode.USAGE
            raise

    @override
    def _main_shell_completion(
        self,
        # Any: click's own type for the context arguments that main() passes through.
        ctx_args: MutableMapping[str, Any],
        prog_name: str,
        complete_var: str | None = None,
    ) -> None:
        """Answer a completion request and exit with 0; return if there is none."""
        variable = complete_var or _complete_var(prog_name)
        instruction = os.environ.get(variable)
        if not instruction:
            return
        response = answer(self, ctx_args, prog_name, instruction)
        if response:
            out(response)
        sys.exit(0)

    @override
    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        """Parse the arguments; a bare `envs` prints the help on stdout and exits with 1.

        Click would raise its private `NoArgsIsHelpError` and print the help on stderr; this
        check runs first, so neither the private class nor stderr is involved. It
        is the one usage error that writes to stdout.
        """
        if not args and self.no_args_is_help and not ctx.resilient_parsing:
            out(ctx.get_help())
            raise typer.Exit(ExitCode.USAGE)
        return super().parse_args(ctx, args)

    @override
    def invoke(self, ctx: "ClickContext") -> object:
        """Run the command; usage errors exit with 1, library errors with their code."""
        try:
            return super().invoke(ctx)
        except typer.TyperException as error:
            error.exit_code = ExitCode.USAGE
            raise
        except EnvironmentStoreError as error:
            err(f"Error: {message_for(error)}")
            raise typer.Exit(exit_code_for(error)) from error


class EnvsCommand(TyperCommand):
    """A command that validates the configuration before its callback runs."""

    resolves_settings: ClassVar[bool] = True
    """Whether the settings are resolved before the callback; `False` for `OfflineCommand`."""

    @override
    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        """Parse the arguments; usage errors get a hint where one helps."""
        try:
            return super().parse_args(ctx, args)
        except typer.TyperException as error:
            hint = self._global_option_hint(ctx, error) or self._store_hint(ctx, error)
            if hint is not None:
                error.message = f"{error.message}; {hint}" if error.message else hint
            raise

    @override
    def invoke(self, ctx: "ClickContext") -> object:
        """Resolve the settings (printing their warnings), then run the callback."""
        if self.resolves_settings:
            # Every context typer creates is a typer.Context at runtime.
            get_state(cast("typer.Context", ctx)).settings()
        return super().invoke(ctx)

    def _global_option_hint(self, ctx: "ClickContext", error: typer.TyperException) -> str | None:
        # Only an unknown option has an option name that is none of this command's own.
        name = getattr(error, "option_name", None)
        if not isinstance(name, str) or ctx.parent is None or _option(self, name) is not None:
            return None
        option = _option(ctx.parent.command, name)
        if option is None:
            return None
        if option.is_eager:
            example = f"{_PROGRAM} {name}"
        elif option.is_flag:
            example = f"{_PROGRAM} {name} {ctx.info_name}"
        else:
            example = f"{_PROGRAM} {name} {option.metavar or 'VALUE'} {ctx.info_name}"
        return f"{name} is a global option: put it before the command, e.g. {example}"

    def _store_hint(self, ctx: "ClickContext", error: typer.TyperException) -> str | None:
        # A missing -s while ENV_STORE_LOAD or the project file lists stores: the user expected
        # them to apply.
        parameter = getattr(error, "param", None)
        if not isinstance(parameter, TyperOption) or parameter.name != _STORE_PARAMETER:
            return None
        try:
            # Every context typer creates is a typer.Context at runtime.
            stores = get_state(cast("typer.Context", ctx)).settings().default_stores
        except EnvironmentStoreError:
            # The usage error is the one to report; the command never ran.
            return None
        return _STORE_HINT if stores else None


class OfflineCommand(EnvsCommand):
    """A command that reads neither the connection nor the project file (`keygen`)."""

    resolves_settings: ClassVar[bool] = False


def _option(command: object, name: str) -> TyperOption | None:
    parameters = getattr(command, "params", ())
    for parameter in parameters:
        if isinstance(parameter, TyperOption) and name in (
            *parameter.opts,
            *parameter.secondary_opts,
        ):
            return parameter
    return None


class PassthroughCommand(EnvsCommand):
    """A command whose arguments after the first `--` are passed through untouched (`run`)."""

    @override
    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        """Split at the first `--`; parse only the part before it."""
        if _SEPARATOR in args:
            index = args.index(_SEPARATOR)
            ctx.meta[PASSTHROUGH] = args[index + 1 :]
            args = args[:index]
        return super().parse_args(ctx, args)


def passthrough_args(ctx: typer.Context) -> list[str] | None:
    """Return the arguments after `--` of a `PassthroughCommand`.

    Args:
        ctx: The command's context.

    Returns:
        The arguments (possibly empty), or `None` if there was no `--`.
    """
    passthrough: list[str] | None = ctx.meta.get(PASSTHROUGH)
    return passthrough
