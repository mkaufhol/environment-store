"""The command line interface `envs` / `environment-store`.

Needs the `cli` extra (typer). This package module imports no typer, so `main()` can report a
missing extra instead of failing with an import error.
"""

import sys

from environment_store.core.errors import MissingExtraError

__all__ = ["main"]


def main() -> None:
    """Run `envs` with `sys.argv`; exits with the command's exit code.

    A missing `cli` extra is reported on stderr with the install hint (exit code 1).
    """
    try:
        from environment_store.cli.app import app  # noqa: PLC0415 - typer is an optional extra
    except MissingExtraError as error:
        sys.stderr.write(f"Error: {error}\n")
        raise SystemExit(1) from None
    app()
