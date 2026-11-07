"""The man page and the tldr page stay in step with the commands of the CLI (D49)."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Final

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app

_ROOT: Final = Path(__file__).parents[2]
_PYPROJECT: Final = _ROOT / "pyproject.toml"
# uv_build installs the contents of the data directory at the install prefix (D49).
_MAN_DATA: Final = "docs/man"
_MAN_DIR: Final = _ROOT / _MAN_DATA / "share" / "man" / "man1"
_MAN_PAGE: Final = _MAN_DIR / "envs.1"
_MAN_ALIAS: Final = _MAN_DIR / "environment-store.1"
_TLDR_PAGE: Final = _ROOT / "docs" / "tldr" / "envs.md"

_SECTIONS: Final = (
    "NAME",
    "SYNOPSIS",
    "DESCRIPTION",
    "GLOBAL OPTIONS",
    "COMMANDS",
    "STORE SELECTION AND KEYS",
    "MERGE ORDER",
    "ENVIRONMENT",
    "FILES",
    "EXIT STATUS",
    "EXAMPLES",
    "SECURITY",
    "SEE ALSO",
)
_EXIT_CODES: Final = range(6)  # D24
_ENVIRONMENT: Final = ("ENV_STORE_CONNECTION", "ENV_STORE_ORDERED_OVERWRITE")
_TLDR_MAX_EXAMPLES: Final = 8
_FONT_ESCAPE: Final = re.compile(r"\\f[BIRP]")
_SECTION_HEADING: Final = re.compile(r'^\.SH\s+"?([^"\n]+?)"?\s*$', re.MULTILINE)
_SUBSECTION_HEADING: Final = re.compile(r'^\.SS\s+"?([^"\n]+?)"?\s*$', re.MULTILINE)


def _group() -> EnvsGroup:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)
    return group


def _registered_commands() -> list[str]:
    return sorted(_group().commands)


def _option_names(command_name: str | None) -> list[str]:
    """Every option name of the root group (None) or of one command, without --help."""
    group = _group()
    command = group if command_name is None else group.commands[command_name]
    names = [
        name
        for parameter in command.params
        if parameter.param_type_name == "option"
        for name in (*parameter.opts, *parameter.secondary_opts)
    ]
    return sorted(names)


def _command_options() -> list[tuple[str, str]]:
    return [
        (command, option) for command in _registered_commands() for option in _option_names(command)
    ]


def _plain(roff: str) -> str:
    """The roff source with escaped hyphens and font changes resolved, for text searches."""
    return _FONT_ESCAPE.sub("", roff.replace("\\-", "-"))


def _split(text: str, heading: re.Pattern[str]) -> dict[str, str]:
    matches = list(heading.finditer(text))
    ends = [match.start() for match in matches[1:]] + [len(text)]
    return {
        _plain(match.group(1)): text[match.end() : end]
        for match, end in zip(matches, ends, strict=True)
    }


def _man_sections() -> dict[str, str]:
    return _split(_MAN_PAGE.read_text(encoding="utf-8"), _SECTION_HEADING)


def _command_sections() -> dict[str, str]:
    return _split(_man_sections()["COMMANDS"], _SUBSECTION_HEADING)


def _mentions(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", _plain(text)) is not None


def _tldr_lines() -> list[str]:
    return _TLDR_PAGE.read_text(encoding="utf-8").splitlines()


def _tldr_examples() -> list[tuple[str, str]]:
    """(description, command) of every example: '- text:', a blank line, '`command`'."""
    lines = _tldr_lines()
    return [
        (line, lines[index + 2] if index + 2 < len(lines) else "")
        for index, line in enumerate(lines)
        if line.startswith("- ")
    ]


def test_pyproject_installs_the_man_directory_as_wheel_data() -> None:
    config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    assert config["tool"]["uv"]["build-backend"]["data"] == {"data": _MAN_DATA}


def test_man_page_lies_where_the_wheel_installs_it_under_share_man() -> None:
    assert _MAN_PAGE.is_file()


def test_environment_store_man_page_is_an_alias_of_envs() -> None:
    assert _MAN_ALIAS.read_text(encoding="utf-8") == ".so man1/envs.1\n"


def test_man_page_has_a_title_line_for_section_one() -> None:
    first = _MAN_PAGE.read_text(encoding="utf-8").splitlines()[0]

    assert first.startswith(".TH ENVS 1 ")


def test_man_page_has_every_section_in_order() -> None:
    assert tuple(_man_sections()) == _SECTIONS


def test_man_page_names_both_executables() -> None:
    name = _plain(_man_sections()["NAME"])

    assert re.match(r"\s*envs, environment-store - \S", name)


def test_man_page_documents_every_registered_command_and_no_other() -> None:
    assert sorted(_command_sections()) == _registered_commands()


@pytest.mark.parametrize(("command", "option"), _command_options())
def test_man_page_documents_every_option_of_every_command(command: str, option: str) -> None:
    assert _mentions(_command_sections()[command], option)


@pytest.mark.parametrize("command", _registered_commands())
def test_man_page_gives_a_synopsis_for_every_command(command: str) -> None:
    assert _mentions(_command_sections()[command], f"envs {command}")


@pytest.mark.parametrize("option", [*_option_names(None), "-h", "--help"])
def test_man_page_documents_every_global_option(option: str) -> None:
    # -h is the shorthand of --help on envs and on every command (D48).
    assert _mentions(_man_sections()["GLOBAL OPTIONS"], option)


@pytest.mark.parametrize("code", _EXIT_CODES)
def test_man_page_documents_every_exit_code(code: int) -> None:
    assert re.search(rf"^\.TP\n\.B {code}\n\S", _man_sections()["EXIT STATUS"], re.MULTILINE)


@pytest.mark.parametrize("variable", _ENVIRONMENT)
def test_man_page_documents_every_environment_variable(variable: str) -> None:
    assert _mentions(_man_sections()["ENVIRONMENT"], variable)


def test_man_page_documents_the_project_file() -> None:
    assert _mentions(_man_sections()["FILES"], ".envstore.toml")


@pytest.mark.skipif(shutil.which("mandoc") is None, reason="mandoc is not installed")
def test_man_page_renders_without_mandoc_warnings() -> None:
    mandoc = shutil.which("mandoc")
    assert mandoc is not None
    result = subprocess.run(  # noqa: S603 - fixed arguments, checked-in file
        [mandoc, "-T", "lint", "-W", "warning", str(_MAN_PAGE)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_tldr_page_starts_with_the_command_name_heading() -> None:
    assert _tldr_lines()[:2] == ["# envs", ""]


def test_tldr_page_describes_the_tool_and_links_more_information() -> None:
    lines = _tldr_lines()
    description = [line for line in lines[2:] if line.startswith("> ")]

    assert lines[2 : 2 + len(description)] == description
    assert len(description) >= 2  # a description and the link line
    assert re.fullmatch(r"> More information: <https://\S+>\.", description[-1])
    assert all(line.endswith(".") for line in description)


def test_tldr_page_has_one_to_eight_examples() -> None:
    assert 1 <= len(_tldr_examples()) <= _TLDR_MAX_EXAMPLES


def test_tldr_page_lines_are_heading_description_examples_or_blank() -> None:
    allowed = re.compile(r"# envs|> .+|- .+:|`.+`|")

    assert [line for line in _tldr_lines() if not allowed.fullmatch(line)] == []


def test_tldr_examples_are_a_description_a_blank_line_and_a_backticked_envs_command() -> None:
    lines = _tldr_lines()
    malformed = [
        (description, command)
        for description, command in _tldr_examples()
        if not re.fullmatch(r"- [A-Z].*:", description)
        or lines[lines.index(description) + 1] != ""
        or not re.fullmatch(r"`envs .+`", command)
    ]

    assert malformed == []


def test_tldr_examples_use_only_registered_commands() -> None:
    commands = set(_registered_commands())
    used = [
        next((word for word in command.strip("`").split() if word in commands), None)
        for _, command in _tldr_examples()
    ]

    assert None not in used


def test_tldr_placeholders_are_balanced() -> None:
    text = _TLDR_PAGE.read_text(encoding="utf-8")

    assert text.count("{{") == text.count("}}")
