"""The only touch points with typer internals: the group and command classes of `envs`.

- `EnvsGroup` maps every typer usage error (unknown command or option, missing argument, bad
  choice) to exit code 1 instead of click's 2, which means "not found" here (D24), and every
  `EnvironmentStoreError` to `Error: <message>` on stderr and its category's exit code.
- `EnvsCommand` resolves the settings before each command's callback (PD 10). `invoke` runs
  only after the command's own arguments were parsed, so `envs <cmd> --help` never resolves
  settings. Every command is registered with `cls=EnvsCommand` (or `PassthroughCommand`).
- `PassthroughCommand` splits the arguments at the first `--` before parsing; the tail is the
  command `run` executes, untouched (C4).
"""

from typing import TYPE_CHECKING, Final, cast, override

import typer
from typer.core import TyperCommand, TyperGroup

from environment_store.cli.errors import ExitCode, exit_code_for
from environment_store.cli.output import err, out
from environment_store.cli.state import get_state
from environment_store.core.errors import EnvironmentStoreError

if TYPE_CHECKING:
    # Type-only: typer's overridable methods are typed with the vendored click Context.
    from typer._click import Context as ClickContext

__all__ = ["EnvsCommand", "EnvsGroup", "PassthroughCommand", "passthrough_args"]

_PASSTHROUGH: Final = "environment_store.passthrough"
_SEPARATOR: Final = "--"


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
    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        """Parse the arguments; a bare `envs` prints the help on stdout and exits with 1.

        Click would raise its private `NoArgsIsHelpError` and print the help on stderr; this
        check runs first, so neither the private class nor stderr is involved (plan §6.3). It
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
            err(f"Error: {error}")
            raise typer.Exit(exit_code_for(error)) from error


class EnvsCommand(TyperCommand):
    """A command that validates the configuration before its callback runs (PD 10)."""

    @override
    def invoke(self, ctx: "ClickContext") -> object:
        """Resolve the settings (printing their warnings), then run the callback."""
        # Every context typer creates is a typer.Context at runtime.
        get_state(cast("typer.Context", ctx)).settings()
        return super().invoke(ctx)


class PassthroughCommand(EnvsCommand):
    """A command whose arguments after the first `--` are passed through untouched (`run`)."""

    @override
    def parse_args(self, ctx: "ClickContext", args: list[str]) -> list[str]:
        """Split at the first `--`; parse only the part before it."""
        if _SEPARATOR in args:
            index = args.index(_SEPARATOR)
            ctx.meta[_PASSTHROUGH] = args[index + 1 :]
            args = args[:index]
        return super().parse_args(ctx, args)


def passthrough_args(ctx: typer.Context) -> list[str] | None:
    """Return the arguments after `--` of a `PassthroughCommand`.

    Args:
        ctx: The command's context.

    Returns:
        The arguments (possibly empty), or `None` if there was no `--`.
    """
    passthrough: list[str] | None = ctx.meta.get(_PASSTHROUGH)
    return passthrough
