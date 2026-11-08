"""The guides explain shell completion (D54) and the TUI's store management (D55-D57)."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from environment_store.cli.app import app
from environment_store.cli.completion.command import Shell

_ROOT: Final = Path(__file__).parents[2]
_BASH: Final = shutil.which("bash")
_CLI_GUIDE: Final = _ROOT / "docs" / "cli.md"
_INSTALLATION: Final = _ROOT / "docs" / "installation.md"
_INDEX: Final = _ROOT / "docs" / "README.md"
_README: Final = _ROOT / "README.md"
_SKILL_DIR: Final = _ROOT / ".claude" / "skills" / "environment-store-cli"
_REFERENCE: Final = _SKILL_DIR / "reference.md"
_DOCUMENTS: Final = (
    _README,
    *sorted((_ROOT / "docs").glob("*.md")),
    *sorted(_SKILL_DIR.glob("*.md")),
)
# The one line per shell of spec §6.15; envs never edits these files itself.
_SETUP_LINES: Final = (
    'eval "$(envs completion zsh)"',
    'eval "$(envs completion bash)"',
    "envs completion fish > ~/.config/fish/completions/envs.fish",
)
_COMPLETION_CALL: Final = re.compile(r"\b(?:envs|environment-store) completion ([a-z]+)")
_HEADING: Final = re.compile(r"^(#{2,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def _text(document: Path) -> str:
    return document.read_text(encoding="utf-8")


def _section(document: Path, title: str) -> str:
    """The text below the heading `title`, up to the next heading of the same or a higher level."""
    text = _text(document)
    headings = list(_HEADING.finditer(text))
    for index, heading in enumerate(headings):
        if heading.group(2) == title:
            level = len(heading.group(1))
            ends = [h.start() for h in headings[index + 1 :] if len(h.group(1)) <= level]
            return text[heading.end() : ends[0] if ends else len(text)]
    pytest.fail(f"no heading {title!r} in {document.name}")


@pytest.mark.parametrize("document", [_CLI_GUIDE, _INSTALLATION, _README, _REFERENCE])
@pytest.mark.parametrize("line", _SETUP_LINES)
def test_the_guides_give_the_setup_line_of_every_shell(document: Path, line: str) -> None:
    assert line in _text(document)


@pytest.mark.parametrize("document", _DOCUMENTS, ids=lambda path: path.name)
def test_every_documented_completion_call_names_a_shell_envs_has(document: Path) -> None:
    shells = set(_COMPLETION_CALL.findall(_text(document)))
    assert shells <= {shell.value for shell in Shell}


@pytest.mark.parametrize("shell", list(Shell))
def test_the_documented_completion_calls_print_a_script(shell: Shell) -> None:
    result = CliRunner().invoke(app, ["completion", shell.value], prog_name="envs")
    assert result.exit_code == 0
    assert "envs" in result.output


@pytest.mark.parametrize(
    "phrase",
    [
        "4.4",  # bash's minimum (compopt, complete -o nosort)
        "Homebrew",  # macOS ships bash 3.2
        "environment-store completion",  # the script completes the name it was run as
        "encrypted",  # never their variable names (no key is read)
        "create-store",  # never a new name
        "read-only",
        "stderr",  # silent
        "ENV_STORE_CONNECTION",  # the backend comes from where the command takes it
    ],
)
def test_the_cli_guide_has_a_shell_completion_section(phrase: str) -> None:
    assert phrase in _section(_CLI_GUIDE, "Shell completion")


def test_the_installation_guide_enables_completion_after_installing() -> None:
    section = _section(_INSTALLATION, "Enable shell completion")
    assert all(line in section for line in _SETUP_LINES)


@pytest.mark.parametrize("key", ["**a**", "**d**", "**x**"])
def test_the_cli_guides_tui_section_lists_the_store_keys(key: str) -> None:
    # D55, D56: create, remove and export on the stores screen.
    assert key in _section(_CLI_GUIDE, "Terminal UI: `tui`")


def test_the_cli_guides_tui_section_no_longer_keeps_creating_and_exporting_on_the_cli() -> None:
    section = " ".join(_section(_CLI_GUIDE, "Terminal UI: `tui`").split())
    assert "Creating, copying, importing, exporting" not in section


@pytest.mark.parametrize(
    "target",
    [
        "cli.md#shell-completion",
        "installation.md#enable-shell-completion",
        "tui.md#create-store",
        "tui.md#remove-store",
        "tui.md#export",
        "tui.md#path-completion",
    ],
)
def test_the_index_links_completion_and_the_tui_flows(target: str) -> None:
    assert f"]({target})" in _text(_INDEX)


def test_the_skill_reference_has_a_completion_section() -> None:
    section = _section(_REFERENCE, "Shell completion")
    assert "never" in section


# Saving the script as a file instead of eval-ing it at every start (Oh My Zsh, fpath,
# bash-completion's on-demand directory) relies on the script's own shape.
@pytest.mark.parametrize("name", ["envs", "environment-store"])
def test_the_zsh_script_can_be_autoloaded_from_fpath(name: str) -> None:
    result = CliRunner().invoke(app, ["completion", "zsh"], prog_name=name)
    assert result.output.startswith(f"#compdef {name}\n")


@pytest.mark.skipif(_BASH is None, reason="bash is not installed")
@pytest.mark.parametrize("name", ["envs", "environment-store"])
def test_the_bash_script_registers_itself_when_sourced_on_demand(name: str, tmp_path: Path) -> None:
    # bash-completion sources the saved file on the first Tab and expects it to call `complete`.
    assert _BASH is not None
    script = tmp_path / name
    script.write_text(
        CliRunner().invoke(app, ["completion", "bash"], prog_name=name).output, encoding="utf-8"
    )
    stubs = 'complete() { printf "%s\\n" "$*"; }; compopt() { :; }; source "$1"'
    result = subprocess.run(  # noqa: S603 - fixed shell and arguments
        [_BASH, "-c", stubs, "bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.stderr == ""
    assert re.fullmatch(rf"-o nosort -F \S+ {re.escape(name)}\n", result.stdout)


@pytest.mark.parametrize(
    "phrase",
    [
        'envs completion zsh > "${ZSH_CUSTOM:-$HOME/.oh-my-zsh/custom}/plugins/envs/_envs"',
        "plugins=(",  # the plugin must be listed in ~/.zshrc
        "#compdef envs",  # why a file named _envs is enough
        "fpath",  # other zsh plugin managers and plain zsh
        ".zcompdump",  # zsh's completion cache can hide a new file
        "$ZDOTDIR",  # where the cache is when it is set
        "bash-completion@2",  # a separate package that must be loaded
        '"${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions/envs"',
        "4.4",  # bash's minimum still applies
        "Do not also keep the `eval` line",
        "after upgrading",  # a saved script is not regenerated by itself
        "`PATH`",  # the saved file still runs envs at every Tab
        "plugins/environment-store/_environment-store",  # the long name, spelled out
    ],
)
def test_the_cli_guide_explains_installing_completion_as_a_file(phrase: str) -> None:
    assert phrase in _section(_CLI_GUIDE, "Saving the script as a file")


def test_the_installation_guide_points_to_the_plugin_manager_setup() -> None:
    section = _section(_INSTALLATION, "Enable shell completion")
    assert "](cli.md#saving-the-script-as-a-file)" in section
    assert "Oh My Zsh" in section


def test_the_skill_reference_mentions_saving_the_script_as_a_file() -> None:
    section = _section(_REFERENCE, "Shell completion")
    assert "_envs" in section
    assert "fpath" in section
    assert "unless the user asked" in section  # agents never set this up on their own
