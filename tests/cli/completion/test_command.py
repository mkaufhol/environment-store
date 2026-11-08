"""`envs completion <shell>` prints the script for the program name in use (§6.15, D44, D54)."""

import pytest
from typer.testing import CliRunner

from environment_store.cli.app import app
from environment_store.cli.completion.protocol import complete_var, program_name
from tests.support.cli import CliHarness, assert_exit


@pytest.mark.parametrize(
    ("prog_name", "variable", "function"),
    [
        ("envs", "_ENVS_COMPLETE", "_envs_completion"),
        ("environment-store", "_ENVIRONMENT_STORE_COMPLETE", "_environment_store_completion"),
    ],
)
@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_the_script_completes_the_program_name_in_use(
    cli_json: CliHarness, prog_name: str, variable: str, function: str, shell: str
) -> None:
    result = CliRunner().invoke(
        app, ["completion", shell], prog_name=prog_name, obj=cli_json.runtime()
    )

    assert_exit(result, 0)
    assert f"{variable}={shell}_complete" in result.stdout
    assert function in result.stdout
    assert f" {prog_name}" in result.stdout
    assert result.stdout.endswith("\n")
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("shell", "marker"),
    [
        ("bash", "complete -o nosort -F _envs_completion envs"),
        ("zsh", "#compdef envs"),
        ("fish", "complete --no-files --command envs"),
    ],
)
def test_each_shell_gets_its_own_script(cli_json: CliHarness, shell: str, marker: str) -> None:
    result = CliRunner().invoke(app, ["completion", shell], prog_name="envs")

    assert marker in result.stdout


def test_completion_needs_no_connection_and_ignores_a_broken_project_file(
    cli_json: CliHarness,
) -> None:
    # D44: like keygen, a broken .envstore.toml cannot stop it, and it prints no warning.
    cli_json.project_file("this is [ not toml")

    result = cli_json.invoke("completion", "zsh", connection=False)

    assert_exit(result, 0)
    assert result.stderr == ""
    assert "compdef" in result.stdout


def test_an_unknown_shell_is_a_usage_error(cli_json: CliHarness) -> None:
    result = cli_json.invoke("completion", "tcsh")

    assert_exit(result, 1)
    assert result.stdout == ""


def test_the_help_shows_how_to_install_the_script(cli_json: CliHarness) -> None:
    result = cli_json.invoke("completion", "--help")

    assert_exit(result, 0)
    assert 'eval "$(envs completion zsh)"' in result.stdout


@pytest.mark.parametrize(
    ("invoked", "expected"),
    [
        ("envs", "envs"),
        ("environment-store", "environment-store"),
        ("python -m environment_store.cli", "envs"),
        ("", "envs"),
        (None, "envs"),
    ],
)
def test_program_name_falls_back_to_envs_for_names_a_shell_cannot_complete(
    invoked: str | None, expected: str
) -> None:
    assert program_name(invoked) == expected


@pytest.mark.parametrize(
    ("prog_name", "expected"),
    [("envs", "_ENVS_COMPLETE"), ("environment-store", "_ENVIRONMENT_STORE_COMPLETE")],
)
def test_complete_var_is_derived_like_click_and_typer(prog_name: str, expected: str) -> None:
    assert complete_var(prog_name) == expected


def test_the_fish_script_puts_the_store_prefix_back_before_completed_paths(
    cli_json: CliHarness,
) -> None:
    # The answer after `-k STORE=` is only the path; fish's token still has `STORE=` in front.
    result = CliRunner().invoke(app, ["completion", "fish"], prog_name="envs")

    assert "string match -r -- '^[^=]*=' \"$token\"" in result.stdout
    assert 'echo "$prefix$path"' in result.stdout
