"""The scripts in real shells, with the installed `envs` / `environment-store` (D54).

zsh runs non-interactively with stubs for the completion builtins, so the generated function
is driven exactly as the completion system calls it. bash is only checked with `bash -n` and
with stubbed `compopt` / `complete`: the bash 3.2 of macOS has neither, the script needs 4.4.
fish is not installed here; its side is covered by the protocol tests.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from tests.support.cli import CliHarness

_BIN: Final = Path(sys.executable).parent
_ZSH: Final = shutil.which("zsh")
_BASH: Final = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    not (_BIN / "envs").exists(), reason="the envs entry point is not installed"
)

_ZSH_STUBS: Final = r"""
compdef() { : }
compadd() { print -rl -- "${(@P)${@[-1]}}" }
_describe() { print -rl -- "${(@P)3}" }
_path_files() { print -r -- "FILES $*" }
compset() { print -r -- "COMPSET $*" }
"""

_BASH_STUBS: Final = r"""
compopt() { echo "COMPOPT $1 $2"; }
complete() { :; }
"""


def _environment(**extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ENV_STORE_", "_ENVS_", "_ENVIRONMENT_STORE_"))
    }
    env["PATH"] = f"{_BIN}{os.pathsep}{env.get('PATH', '')}"
    return {**env, **extra}


def _run(command: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed shells and arguments
        command, capture_output=True, text=True, check=False, cwd=cwd, env=dict(env), timeout=60
    )


def _script(prog_name: str, shell: str, cwd: Path) -> str:
    result = _run([str(_BIN / prog_name), "completion", shell], cwd, _environment())
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return result.stdout


def _zsh(cli: CliHarness, prog_name: str, words: list[str]) -> list[str]:
    assert _ZSH is not None
    script = cli.root / "completion.zsh"
    script.write_text(_script(prog_name, "zsh", cli.root), encoding="utf-8")
    quoted = " ".join(f"'{word}'" for word in words)
    function = "_" + prog_name.replace("-", "_") + "_completion"
    body = (
        f"{_ZSH_STUBS}\nsource {script}\n"
        f"words=({quoted})\nCURRENT={len(words)}\nPREFIX='{words[-1]}'\n{function}\n"
    )
    result = _run([_ZSH, "-f", "-c", body], cli.root, _environment())
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    return result.stdout.splitlines()


@pytest.mark.skipif(_ZSH is None, reason="zsh is not installed")
@pytest.mark.parametrize("prog_name", ["envs", "environment-store"])
def test_zsh_completes_store_names(cli_json: CliHarness, prog_name: str) -> None:
    cli_json.store().create_store("alpha")
    cli_json.store().create_store("beta")

    lines = _zsh(cli_json, prog_name, [prog_name, "-c", cli_json.connection, "ls", ""])

    assert lines == ["alpha", "beta"]


@pytest.mark.skipif(_ZSH is None, reason="zsh is not installed")
def test_zsh_describes_commands_with_their_help(cli_json: CliHarness) -> None:
    lines = _zsh(cli_json, "envs", ["envs", "ls"])

    assert any(line.startswith("ls-store:List all stores") for line in lines)


@pytest.mark.skipif(_ZSH is None, reason="zsh is not installed")
def test_zsh_completes_the_path_after_store_equals_with_its_own_file_completion(
    cli_json: CliHarness,
) -> None:
    cli_json.store().create_store("alpha")

    lines = _zsh(cli_json, "envs", ["envs", "-c", cli_json.connection, "ls", "-k", "alpha=ke"])

    assert lines == ["COMPSET -P *=", "FILES -f"]


@pytest.mark.skipif(_ZSH is None, reason="zsh is not installed")
def test_zsh_completes_a_plain_path_without_stripping_anything(cli_json: CliHarness) -> None:
    lines = _zsh(cli_json, "envs", ["envs", "keygen", "a=b"])

    assert lines == ["FILES -f"]


@pytest.mark.skipif(_BASH is None, reason="bash is not installed")
@pytest.mark.parametrize("prog_name", ["envs", "environment-store"])
def test_the_bash_script_has_valid_syntax(tmp_path: Path, prog_name: str) -> None:
    assert _BASH is not None
    script = tmp_path / "completion.bash"
    script.write_text(_script(prog_name, "bash", tmp_path), encoding="utf-8")

    result = _run([_BASH, "-n", str(script)], tmp_path, _environment())

    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.skipif(_BASH is None, reason="bash is not installed")
@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["ls", ""], ["alpha", "beta"]),
        (["ls", "-k", "al"], ["COMPOPT -o nospace", "alpha="]),
        (["keygen", "ke"], ["COMPOPT -o default"]),
    ],
)
def test_the_bash_function_fills_compreply(
    cli_json: CliHarness, words: list[str], expected: list[str]
) -> None:
    assert _BASH is not None
    cli_json.store().create_store("alpha")
    cli_json.store().create_store("beta")
    script = cli_json.root / "completion.bash"
    script.write_text(_script("envs", "bash", cli_json.root), encoding="utf-8")
    line = ["envs", "-c", cli_json.connection, *words]
    body = (
        f"{_BASH_STUBS}\nsource {script}\n"
        f"COMP_WORDS=({' '.join(repr(word) for word in line)})\n"
        f"COMP_CWORD={len(line) - 1}\n_envs_completion envs\n"
        'for reply in "${COMPREPLY[@]}"; do echo "$reply"; done\n'
    )

    result = _run([_BASH, "--norc", "--noprofile", "-c", body], cli_json.root, _environment())

    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.splitlines() == expected


@pytest.mark.parametrize(
    ("prog_name", "variable"),
    [("envs", "_ENVS_COMPLETE"), ("environment-store", "_ENVIRONMENT_STORE_COMPLETE")],
)
def test_both_entry_points_answer_the_protocol(
    cli_json: CliHarness, prog_name: str, variable: str
) -> None:
    cli_json.store().create_store("alpha")
    env = _environment(
        **{
            variable: "fish_complete",
            "COMP_WORDS": f"{prog_name} -c {cli_json.connection} rm-store al",
            "COMP_CWORD": "al",
        }
    )

    result = _run([str(_BIN / prog_name)], cli_json.root, env)

    assert (result.returncode, result.stdout, result.stderr) == (0, "plain,alpha\n", "")
