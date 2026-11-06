"""`envs migrate`: create or upgrade the SQL schema (D11, D13, PD 22)."""

import typer

from environment_store.cli._typer import EnvsCommand
from environment_store.cli.output import err
from environment_store.cli.state import get_state
from environment_store.core.adapter import MigrationReport, SetupMode

__all__ = ["migrate", "register"]


def register(app: typer.Typer) -> None:
    """Register `migrate` on the app.

    Args:
        app: The `envs` app.
    """
    app.command("migrate", cls=EnvsCommand)(migrate)


def migrate(ctx: typer.Context) -> None:
    """Create or upgrade the SQL schema (SQLite, PostgreSQL)."""
    # NONE: opening must not refuse an outdated schema that this command is meant to upgrade.
    store = get_state(ctx).open_store(ctx, setup=SetupMode.NONE)
    err(_describe(store.migrate()))


def _describe(report: MigrationReport) -> str:
    if report.from_version is None:
        return f"created schema v{report.to_version}"
    if report.from_version < report.to_version:
        return f"upgraded schema from v{report.from_version} to v{report.to_version}"
    return f"schema is up to date (v{report.to_version})"
