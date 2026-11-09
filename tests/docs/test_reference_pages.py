"""The man page and the tldr page stay in step with the commands of the CLI."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Final, NamedTuple

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app
from environment_store.core.merge import merge

_ROOT: Final = Path(__file__).parents[2]
_PYPROJECT: Final = _ROOT / "pyproject.toml"
# uv_build installs the contents of the data directory at the install prefix.
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
_EXIT_CODES: Final = range(6)  # the exit codes 0-5 of envs
_ENVIRONMENT: Final = (
    "ENV_STORE_CONNECTION",
    "ENV_STORE_ORDERED_OVERWRITE",
    "ENV_STORE_KEY_",
    "ENV_STORE_LOAD",
)
_TLDR_MAX_EXAMPLES: Final = 8
_FONT_ESCAPE: Final = re.compile(r"\\f[BIRP]")
_SECTION_HEADING: Final = re.compile(r'^\.SH\s+"?([^"\n]+?)"?\s*$', re.MULTILINE)
_SUBSECTION_HEADING: Final = re.compile(r'^\.SS\s+"?([^"\n]+?)"?\s*$', re.MULTILINE)
# An option name as the page or an example writes it: -x or --long-name, not the
# hyphen inside a word such as ls-store.
_FLAG: Final = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
_HELP_OPTIONS: Final = ("-h", "--help")


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


def _value_options(command_name: str | None) -> set[str]:
    """The option names of the root group (None) or of one command that take a value."""
    group = _group()
    command = group if command_name is None else group.commands[command_name]
    return {
        name
        for parameter in command.params
        # Duck-typed: typer vendors click privately, so tests import neither click nor typer._click.
        if parameter.param_type_name == "option" and not getattr(parameter, "is_flag", False)
        for name in parameter.opts
    }


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


def _tagged_paragraph_heads(body: str) -> str:
    """The head line of every .TP paragraph: where an option is defined."""
    lines = body.split("\n")
    return "\n".join(lines[index + 1] for index, line in enumerate(lines[:-1]) if line == ".TP")


def _documented_flags(body: str, *, synopsis: bool) -> list[str]:
    """Every option name the synopsis (text before the first .PP) or a .TP head defines.

    Option names in running text, such as a reference to another command's option,
    are not definitions and are left out.
    """
    defining = _tagged_paragraph_heads(body)
    if synopsis:
        defining = body.split("\n.PP", 1)[0] + "\n" + defining
    return sorted(set(_FLAG.findall(_plain(defining))))


def _documented_command_options() -> list[tuple[str, str]]:
    return [
        (command, option)
        for command, body in _command_sections().items()
        for option in _documented_flags(body, synopsis=True)
    ]


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


class _Invocation(NamedTuple):
    """The words of a tldr example that name options and the subcommand."""

    global_options: list[str]
    command: str | None
    options: list[str]


def _option_words(words: list[str]) -> list[str]:
    """The option names among words; an ``--option=value`` counts as ``--option``."""
    names = [word.split("=", 1)[0] for word in words]
    return [name for name in names if _FLAG.fullmatch(name)]


def _tldr_invocation(example: str) -> _Invocation:
    """The global options, the subcommand and its options of a tldr example.

    The subcommand is the first word after ``envs`` that is neither a global option
    nor the value of one. Its options are read up to a ``--`` that ends them.
    """
    words = example.strip("`").split()[1:]
    global_values = _value_options(None)
    index = 0
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in global_values else 1
    global_options = _option_words(words[:index])
    if index >= len(words):
        return _Invocation(global_options, None, [])
    rest = words[index + 1 :]
    options = rest[: rest.index("--")] if "--" in rest else rest
    return _Invocation(global_options, words[index], _option_words(options))


def _tldr_invocations() -> list[_Invocation]:
    return [_tldr_invocation(command) for _, command in _tldr_examples()]


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


def test_man_page_installs_envs_from_pypi() -> None:
    text = _plain(_man_sections()["DESCRIPTION"]).replace("\\(dq", '"')

    assert 'uv tool install "environment-store[cli]"' in text


def test_man_page_installs_nothing_from_a_git_url() -> None:
    # 2.0 is on PyPI; a Git URL would pin readers to an unreleased branch.
    assert "git+" not in _plain(_MAN_PAGE.read_text(encoding="utf-8"))


def test_man_page_documents_every_registered_command_and_no_other() -> None:
    assert sorted(_command_sections()) == _registered_commands()


@pytest.mark.parametrize(("command", "option"), _command_options())
def test_man_page_documents_every_option_of_every_command(command: str, option: str) -> None:
    assert _mentions(_command_sections()[command], option)


@pytest.mark.parametrize(("command", "option"), _documented_command_options())
def test_man_page_documents_only_options_the_command_has(command: str, option: str) -> None:
    # The reverse of the test above: a removed or renamed option must not stay
    # documented.
    assert option in [*_option_names(command), *_HELP_OPTIONS]


def test_documented_flags_come_from_the_synopsis_and_the_tagged_paragraph_heads() -> None:
    body = (
        "\n.B envs x\n.RB [ \\-a ]\n.PP\nText about \\-\\-other and ls\\-store.\n"
        '.TP\n.BR \\-b ", " \\-\\-bee\nMeans \\-\\-not\\-this.\n'
    )

    assert _documented_flags(body, synopsis=True) == ["--bee", "-a", "-b"]
    assert _documented_flags(body, synopsis=False) == ["--bee", "-b"]


@pytest.mark.parametrize("command", _registered_commands())
def test_man_page_gives_a_synopsis_for_every_command(command: str) -> None:
    assert _mentions(_command_sections()[command], f"envs {command}")


def test_documented_help_options_are_the_help_options_of_the_cli() -> None:
    # The man page follows the merged CLI: -h is the shorthand of --help.
    assert tuple(_group().context_settings["help_option_names"]) == _HELP_OPTIONS


@pytest.mark.parametrize("option", [*_option_names(None), *_HELP_OPTIONS])
def test_man_page_documents_every_global_option(option: str) -> None:
    # -h is the shorthand of --help on envs and on every command.
    assert _mentions(_man_sections()["GLOBAL OPTIONS"], option)


@pytest.mark.parametrize(
    "option", _documented_flags(_man_sections()["GLOBAL OPTIONS"], synopsis=False)
)
def test_man_page_documents_only_global_options_envs_has(option: str) -> None:
    assert option in [*_option_names(None), *_HELP_OPTIONS]


@pytest.mark.parametrize("option", _HELP_OPTIONS)
def test_man_page_names_every_help_option_among_those_that_skip_the_connection(
    option: str,
) -> None:
    # Help, under either name, reads neither the connection nor the project file.
    paragraph = next(
        paragraph
        for paragraph in _man_sections()["GLOBAL OPTIONS"].split("\n.PP")
        if "read neither the connection" in _plain(paragraph)
    )

    assert _mentions(paragraph, option)


def test_man_page_merge_example_shows_the_merged_output_order() -> None:
    # Store load order, sorted by name within a store, a shared variable keeps its
    # first position. The inputs are the ones the MERGE ORDER section names.
    section = _man_sections()["MERGE ORDER"]
    stores = [
        ("a", {"ENV": "development", "DEBUG": "True"}),
        ("b", {"ENV": "staging", "DB_NAME": "test"}),
    ]
    example = re.search(r"^\.nf\n(.*?)^\.fi$", section, re.MULTILINE | re.DOTALL)

    assert example is not None
    assert all(
        _mentions(section, f"{name}={value}")
        for _, variables in stores
        for name, value in variables.items()
    )
    assert _mentions(section, "envs export a b")
    assert example.group(1).splitlines() == [
        f"{name}={value}" for name, value in merge(stores).items()
    ]


@pytest.mark.parametrize("code", _EXIT_CODES)
def test_man_page_documents_every_exit_code(code: int) -> None:
    assert re.search(rf"^\.TP\n\.B {code}\n\S", _man_sections()["EXIT STATUS"], re.MULTILINE)


@pytest.mark.parametrize("variable", _ENVIRONMENT)
def test_man_page_documents_every_environment_variable(variable: str) -> None:
    assert _mentions(_man_sections()["ENVIRONMENT"], variable)


def test_man_page_documents_the_project_file() -> None:
    assert _mentions(_man_sections()["FILES"], ".envstore.toml")


@pytest.mark.parametrize(
    "phrase",
    [
        "_envs",
        "fpath",
        "compinit",
        "#compdef envs",
        "bash-completion/completions",
        "after upgrading",
    ],
)
def test_man_page_completion_section_explains_saving_the_script_as_a_file(phrase: str) -> None:
    assert phrase in _plain(_command_sections()["completion"])


@pytest.mark.parametrize("phrase", ["create", "remove", "export", "path completion"])
def test_man_page_tui_section_names_store_management_export_and_path_completion(
    phrase: str,
) -> None:
    # As docs/tui.md describes them.
    assert _mentions(_command_sections()["tui"], phrase), phrase


def test_man_page_tui_section_lists_the_new_keys() -> None:
    # The stores screen's a, d and x, and Tab in a path input.
    heads = _plain(_tagged_paragraph_heads(_command_sections()["tui"])).split("\n")
    assert [head.split()[-1] for head in heads] == ["a", "d", "x", "Tab"]


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


@pytest.mark.parametrize(
    ("example", "expected"),
    [
        ("`envs bogus-cmd {{store}} ls`", _Invocation([], "bogus-cmd", [])),
        ("`envs lst ls-store`", _Invocation([], "lst", [])),
        (
            "`envs --connection json://{{dir}} -c x ls-store --json`",
            _Invocation(["--connection", "-c"], "ls-store", ["--json"]),
        ),
        (
            "`envs --noinput set -s {{store}} --file={{f}} {{KEY}}`",
            _Invocation(["--noinput"], "set", ["-s", "--file"]),
        ),
        ("`envs run {{store}} -- {{command}} --flag`", _Invocation([], "run", [])),
        ("`envs --version`", _Invocation(["--version"], None, [])),
        ("`envs --connection`", _Invocation(["--connection"], None, [])),
    ],
)
def test_tldr_invocation_reads_the_subcommand_after_global_options_and_its_options(
    example: str, expected: _Invocation
) -> None:
    assert _tldr_invocation(example) == expected


def test_tldr_examples_use_only_registered_commands() -> None:
    commands = set(_registered_commands())

    used = [invocation.command for invocation in _tldr_invocations()]

    assert [command for command in used if command not in commands] == []


def test_tldr_examples_use_only_options_their_command_has() -> None:
    unknown = [
        (command, option)
        for _, command, options in _tldr_invocations()
        if command is not None
        for option in options
        if option not in [*_option_names(command), *_HELP_OPTIONS]
    ]

    assert unknown == []


def test_tldr_examples_use_only_global_options_envs_has() -> None:
    global_options = [*_option_names(None), *_HELP_OPTIONS]
    unknown = [
        option
        for invocation in _tldr_invocations()
        for option in invocation.global_options
        if option not in global_options
    ]

    assert unknown == []


def test_tldr_placeholders_are_balanced() -> None:
    text = _TLDR_PAGE.read_text(encoding="utf-8")

    assert text.count("{{") == text.count("}}")
