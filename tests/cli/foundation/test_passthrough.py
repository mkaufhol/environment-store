"""`PassthroughCommand`: everything after the first `--` reaches `run` untouched (PD 28)."""

import json

import pytest
import typer

from environment_store.cli._typer import PassthroughCommand, passthrough_args
from environment_store.cli.app import build_app
from environment_store.cli.options import OverwriteOpt, StoresArg
from environment_store.cli.output import out
from tests.support.cli import CliHarness, assert_exit


@pytest.fixture
def app() -> typer.Typer:
    app = build_app()

    @app.command("run", cls=PassthroughCommand)
    def run(
        ctx: typer.Context, stores: StoresArg = None, *, overwrite: OverwriteOpt = False
    ) -> None:
        out(json.dumps({"stores": stores, "o": overwrite, "cmd": passthrough_args(ctx)}))

    return app


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["a", "b", "-o", "--", "python", "-c", "1", "-o"],
            {"stores": ["a", "b"], "o": True, "cmd": ["python", "-c", "1", "-o"]},
        ),
        (
            ["a", "--", "x", "--", "--help"],
            {"stores": ["a"], "o": False, "cmd": ["x", "--", "--help"]},
        ),
        (["a", "--"], {"stores": ["a"], "o": False, "cmd": []}),
        (["a"], {"stores": ["a"], "o": False, "cmd": None}),
        (["--", "env"], {"stores": None, "o": False, "cmd": ["env"]}),
    ],
)
def test_arguments_after_the_separator_are_untouched(
    cli_json: CliHarness, app: typer.Typer, args: list[str], expected: dict[str, object]
) -> None:
    result = cli_json.invoke("run", *args, app=app)

    assert_exit(result, 0)
    assert json.loads(result.stdout) == expected


def test_options_before_the_separator_are_still_parsed(
    cli_json: CliHarness, app: typer.Typer
) -> None:
    result = cli_json.invoke("run", "--bogus", "--", "x", app=app)

    assert_exit(result, 1)
    assert "No such option" in result.stderr
