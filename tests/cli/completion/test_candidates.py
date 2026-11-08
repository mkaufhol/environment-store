"""The completion callbacks and parameter types, called directly (D54)."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import cast

import typer
from typer.core import TyperGroup
from typer.main import get_command

from environment_store.cli.app import app
from environment_store.cli.completion.candidates import (
    PathType,
    ReadKeyType,
    complete_stores,
    complete_variables,
)
from tests.support.cli import CliHarness


@contextmanager
def _context(cli: CliHarness, *args: str) -> Generator[typer.Context]:
    """The command context of `envs -c <connection> args...`, parsed leniently like completion."""
    group = get_command(app)
    assert isinstance(group, TyperGroup)
    arguments = ["-c", cli.connection, *args]
    with group.make_context("envs", arguments, resilient_parsing=True, obj=cli.runtime()) as root:
        name, command, rest = group.resolve_command(root, [args[0], *args[1:]])
        assert command is not None
        with command.make_context(name, rest, parent=root, resilient_parsing=True) as ctx:
            # At runtime a completion context is click's own class; typer.Context is its type.
            yield cast("typer.Context", ctx)


def test_complete_stores_lists_matching_store_names(cli_json: CliHarness) -> None:
    for name in ("alpha", "beta", "base"):
        cli_json.store().create_store(name)

    with _context(cli_json, "ls") as ctx:
        assert complete_stores(ctx, "") == ["alpha", "base", "beta"]
        assert complete_stores(ctx, "ba") == ["base"]


def test_complete_stores_without_a_connection_is_empty(cli_json: CliHarness) -> None:
    group = get_command(app)
    assert isinstance(group, TyperGroup)
    runtime = cli_json.runtime()
    with group.make_context(
        "envs", ["--no-project", "ls"], resilient_parsing=True, obj=runtime
    ) as ctx:
        assert complete_stores(cast("typer.Context", ctx), "") == []


def test_complete_variables_uses_the_store_of_s(cli_json: CliHarness) -> None:
    cli_json.store().create_store("alpha")
    cli_json.store().set_many("alpha", {"B": "2", "A": "1"})

    with _context(cli_json, "rm", "-s", "alpha") as ctx:
        assert complete_variables(ctx, "") == ["A", "B"]


def test_complete_variables_uses_the_positional_stores(cli_json: CliHarness) -> None:
    for name in ("alpha", "beta"):
        cli_json.store().create_store(name)
    cli_json.store().set("alpha", "A", "1")
    cli_json.store().set("beta", "B", "1")

    with _context(cli_json, "ls", "beta", "beta") as ctx:
        assert complete_variables(ctx, "") == ["B"]


def test_complete_variables_without_stores_is_empty(cli_json: CliHarness) -> None:
    with _context(cli_json, "get") as ctx:
        assert complete_variables(ctx, "") == []


def test_path_type_passes_the_value_through_and_asks_for_files(cli_json: CliHarness) -> None:
    path_type = PathType()

    with _context(cli_json, "keygen") as ctx:
        param = ctx.command.params[0]
        assert path_type.convert("-", param, ctx) == "-"
        items = path_type.shell_complete(ctx, param, "ke")

    assert [(item.type, item.value) for item in items] == [("file", "ke")]


def test_read_key_type_offers_store_names_then_the_path(cli_json: CliHarness) -> None:
    cli_json.store().create_store("alpha")
    key_type = ReadKeyType()

    with _context(cli_json, "ls") as ctx:
        param = ctx.command.params[0]
        stores = key_type.shell_complete(ctx, param, "a")
        path = key_type.shell_complete(ctx, param, "alpha=~/k")
        bare = key_type.shell_complete(ctx, param, "./a=b")

    assert [(item.type, item.value) for item in stores] == [("plain", "alpha=")]
    assert [(item.type, item.value) for item in path] == [("file", "~/k")]
    assert bare == []
