"""The user documentation and the agent skill stay in sync with the CLI and with each other."""

import re
import shlex
import tomllib
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app
from environment_store.core.connection import ADAPTER_FACTORIES
from environment_store.core.errors import MissingExtraError
from tests.unit.test_import_direction import ALLOWED_IMPORTS

_ROOT: Final = Path(__file__).parents[2]
_CLI_GUIDE: Final = _ROOT / "docs" / "cli.md"
_SKILL_DIR: Final = _ROOT / ".claude" / "skills" / "environment-store-cli"
_SKILL: Final = _SKILL_DIR / "SKILL.md"
_DEVELOPER_GUIDE: Final = _ROOT / "docs" / "development"
_DOCUMENTS: Final = (
    _ROOT / "README.md",
    *sorted((_ROOT / "docs").glob("*.md")),
    *sorted(_DEVELOPER_GUIDE.glob("*.md")),
    *sorted(_SKILL_DIR.glob("*.md")),
)
# Documents whose relative links must resolve: the documentation plus the contributor rules.
_LINKED_DOCUMENTS: Final = (*_DOCUMENTS, _ROOT / "CLAUDE.md", _ROOT / "CONTRIBUTING.md")

_FENCE: Final = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_CODE_SPAN: Final = re.compile(r"`([^`\n]+)`")
_HEADING: Final = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
# [text](target) and ![alt](target), optionally followed by a "title".
_MARKDOWN_LINK: Final = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_LINK: Final = re.compile(r"""\b(?:href|src)=["']([^"']+)["']""")
_EXTERNAL: Final = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_HTML_ANCHOR: Final = re.compile(r"""<a\s+(?:name|id)=["']([^"']+)["']""")
# A quoted MissingExtraError message, up to the end of its line or of its code span.
_MISSING_EXTRA: Final = re.compile(r"this feature needs the optional '(\w+)' dependencies: [^`\n]*")
_MAN_PAGE: Final = _ROOT / "docs" / "man" / "share" / "man" / "man1" / "envs.1"
_CHANGELOG: Final = _ROOT / "CHANGELOG.md"
_PROJECT_FILES: Final = (
    *_DOCUMENTS,
    _MAN_PAGE,
    _CHANGELOG,
    _ROOT / "CLAUDE.md",
    _ROOT / "CONTRIBUTING.md",
)
# `environment-store 2.0.0` as `envs --version` prints it, or a bare version in a code span.
_SHOWN_VERSION: Final = re.compile(r"environment-store (\d[\w.]*)|`'?(\d+\.\d+\.\d+[\w.]*)'?`")
_REPOSITORY: Final = "https://github.com/mkaufhol/environment-store"


def _registered_commands() -> list[str]:
    group = get_command(app)
    assert isinstance(group, EnvsGroup)
    return sorted(group.commands)


def _prose(document: Path) -> str:
    """The document without fenced code blocks, whose `#` lines and brackets are not Markdown."""
    return _FENCE.sub("", document.read_text(encoding="utf-8"))


def _mentioned_words(document: Path) -> set[str]:
    """Every word of every heading and inline code span, e.g. `envs cp-store --plain` -> 3 words."""
    prose = _prose(document)
    texts = [*_HEADING.findall(prose), *_CODE_SPAN.findall(prose)]
    return {word.strip("`") for text in texts for word in text.split()}


def _relative_links(document: Path) -> list[str]:
    prose = _CODE_SPAN.sub("", _prose(document))
    targets = [*_MARKDOWN_LINK.findall(prose), *_HTML_LINK.findall(prose)]
    return [target for target in targets if not _EXTERNAL.match(target)]


def _github_slug(heading: str) -> str:
    """The anchor GitHub generates for a heading: lower case, punctuation dropped, spaces to `-`."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(document: Path) -> set[str]:
    prose = _prose(document)
    anchors = set(_HTML_ANCHOR.findall(prose))
    seen: dict[str, int] = {}
    for heading in _HEADING.findall(prose):
        slug = _github_slug(heading)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def _package_version() -> str:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert isinstance(version, str)
    return version


def _document_id(document: Path) -> str:
    return document.relative_to(_ROOT).as_posix()


def test_documentation_set_contains_readme_guides_and_skill() -> None:
    names = {_document_id(document) for document in _DOCUMENTS}

    assert {"README.md", "docs/README.md", "docs/cli.md", "docs/python.md"} <= names
    assert {".claude/skills/environment-store-cli/SKILL.md"} <= names


@pytest.mark.parametrize("command", _registered_commands())
def test_cli_guide_mentions_every_registered_command(command: str) -> None:
    assert command in _mentioned_words(_CLI_GUIDE)


@pytest.mark.parametrize("command", _registered_commands())
def test_agent_skill_mentions_every_registered_command(command: str) -> None:
    assert command in _mentioned_words(_SKILL)


@pytest.mark.parametrize("document", _LINKED_DOCUMENTS, ids=_document_id)
def test_relative_links_point_to_existing_files(document: Path) -> None:
    missing = [
        target
        for target in _relative_links(document)
        if target.partition("#")[0] and not (document.parent / target.partition("#")[0]).exists()
    ]

    assert missing == []


@pytest.mark.parametrize("document", _LINKED_DOCUMENTS, ids=_document_id)
def test_relative_links_to_markdown_headings_point_to_existing_anchors(document: Path) -> None:
    broken: list[str] = []
    for target in _relative_links(document):
        path, _, anchor = target.partition("#")
        linked = document.parent / path if path else document
        if (
            anchor
            and linked.suffix == ".md"
            and linked.is_file()
            and anchor not in _anchors(linked)
        ):
            broken.append(target)

    assert broken == []


def test_documentation_index_links_every_guide() -> None:
    linked = {target.partition("#")[0] for target in _relative_links(_ROOT / "docs" / "README.md")}
    guides = {path.name for path in (_ROOT / "docs").glob("*.md") if path.name != "README.md"}

    assert guides <= linked


def _links_to(document: Path) -> set[Path]:
    return {
        (document.parent / target.partition("#")[0]).resolve()
        for target in _relative_links(document)
        if target.partition("#")[0]
    }


def test_developer_guide_index_links_every_page_of_the_guide() -> None:
    pages = {page.resolve() for page in _DEVELOPER_GUIDE.glob("*.md") if page.name != "README.md"}

    assert pages
    assert pages <= _links_to(_DEVELOPER_GUIDE / "README.md")


@pytest.mark.parametrize(
    "document",
    [_ROOT / "docs" / "README.md", _ROOT / "CONTRIBUTING.md", _ROOT / "CLAUDE.md"],
    ids=_document_id,
)
def test_the_developer_guide_is_linked_from_the_index_and_the_contributor_rules(
    document: Path,
) -> None:
    assert (_DEVELOPER_GUIDE / "README.md").resolve() in _links_to(document)


# `src/environment_store/core/merge.py`, `tests/support/cli.py::CliHarness`, `pyproject.toml:12`.
_REPOSITORY_PATH: Final = re.compile(
    r"((?:src|tests|docs|\.github|\.claude)/[\w./-]*[\w/]|pyproject\.toml|CHANGELOG\.md|"
    r"CONTRIBUTING\.md|CLAUDE\.md|\.pre-commit-config\.yaml)(?:::(\w+)|:\d+(?:-\d+)?)?"
)


def _developer_guide_paths() -> list[tuple[str, str, str]]:
    return [
        (page.name, match.group(1), match.group(2) or "")
        for page in sorted(_DEVELOPER_GUIDE.glob("*.md"))
        for span in _CODE_SPAN.findall(_FENCE.sub("", page.read_text(encoding="utf-8")))
        if (match := _REPOSITORY_PATH.fullmatch(span))
    ]


def test_the_developer_guide_names_repository_paths() -> None:
    assert len(_developer_guide_paths()) > 50


@pytest.mark.parametrize(("page", "path", "name"), _developer_guide_paths())
def test_every_path_the_developer_guide_names_exists(page: str, path: str, name: str) -> None:
    target = _ROOT / path

    assert target.exists(), f"{page} names {path}, which does not exist"
    if name:
        assert re.search(rf"\b{name}\b", target.read_text(encoding="utf-8")), (
            f"{page} names {path}::{name}, which the file does not define or use"
        )


# | `cli` | `core`, `config`, `library`, `formats`, `cli` |
_LAYER_ROW: Final = re.compile(r"^\| `([\w.]+)` \| ((?:`[\w.]+`(?:, )?)+) \|", re.MULTILINE)


def test_architecture_guide_shows_the_enforced_import_rules() -> None:
    guide = (_DEVELOPER_GUIDE / "architecture.md").read_text(encoding="utf-8")
    documented = {
        layer: frozenset(re.findall(r"`([\w.]+)`", allowed))
        for layer, allowed in _LAYER_ROW.findall(guide)
    }

    assert documented == ALLOWED_IMPORTS


@pytest.mark.parametrize("scheme", sorted(ADAPTER_FACTORIES))
def test_adapter_guide_names_every_registered_scheme(scheme: str) -> None:
    guide = (_DEVELOPER_GUIDE / "adapters.md").read_text(encoding="utf-8")

    assert f"`{scheme}://" in guide


def test_python_guide_names_every_public_name_of_the_library() -> None:
    import environment_store  # noqa: PLC0415 - only this test needs the package's names

    guide = (_ROOT / "docs" / "python.md").read_text(encoding="utf-8")
    missing = [
        name
        for name in environment_store.__all__
        if re.search(rf"\b{re.escape(name)}\b", guide) is None
    ]
    assert missing == []


def test_python_guide_quotes_no_cli_flags_in_library_errors() -> None:
    # Library errors name library parameters; a quoted error with `-k` or `(--force)`
    # would be CLI wording.
    guide = (_ROOT / "docs" / "python.md").read_text(encoding="utf-8")
    quoted = re.findall(r"^.*\b[A-Z][A-Za-z]*Error: .*$", guide, re.MULTILINE)
    assert quoted
    flags = re.compile(r"(?:^|[\s(/'\"])--?[a-z]|\benvs\b|\bkeygen\b")
    assert [line for line in quoted if flags.search(line.split("Error: ", 1)[1])] == []


@pytest.mark.parametrize("document", [*_DOCUMENTS, _MAN_PAGE], ids=_document_id)
def test_quoted_missing_extra_messages_match_the_error(document: Path) -> None:
    text = document.read_text(encoding="utf-8").replace("\\-", "-")
    quoted = [(match.group(0), match.group(1)) for match in _MISSING_EXTRA.finditer(text)]

    assert [line for line, extra in quoted if line != str(MissingExtraError(extra))] == []


@pytest.mark.parametrize("document", _DOCUMENTS, ids=lambda path: path.name)
def test_no_document_claims_there_is_no_shell_completion(document: Path) -> None:
    # `envs completion` exists; an older sentence saying otherwise would mislead.
    prose = " ".join(document.read_text(encoding="utf-8").split())
    assert not re.search(r"\bno (?:built-in )?shell completion\b", prose, re.IGNORECASE)


@pytest.mark.parametrize("document", _PROJECT_FILES, ids=_document_id)
def test_no_document_points_to_the_feature_branch(document: Path) -> None:
    # main is the base branch since 2.0; feature/v2 links break once it is deleted.
    assert "feature/v2" not in document.read_text(encoding="utf-8")


def test_readme_has_only_absolute_links() -> None:
    # PyPI renders the README without the repository, so a relative link would break there.
    assert _relative_links(_ROOT / "README.md") == []


def test_readme_links_into_the_repository_point_to_main() -> None:
    prose = _prose(_ROOT / "README.md")
    targets = [*_MARKDOWN_LINK.findall(prose), *_HTML_LINK.findall(prose)]
    repository = [target for target in targets if target.startswith(f"{_REPOSITORY}/")]

    assert repository
    assert [
        target
        for target in repository
        if not target.startswith((f"{_REPOSITORY}/blob/main/", f"{_REPOSITORY}/tree/main/"))
    ] == []


@pytest.mark.parametrize("document", _DOCUMENTS, ids=_document_id)
def test_documented_versions_are_the_package_version(document: Path) -> None:
    # Sample output such as `envs --version` must stay real across releases.
    shown = {
        printed or quoted
        for printed, quoted in _SHOWN_VERSION.findall(document.read_text(encoding="utf-8"))
    }

    assert shown <= {_package_version()}


def test_package_is_a_final_release() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", _package_version())


def test_changelog_has_an_entry_for_the_package_version() -> None:
    changelog = _CHANGELOG.read_text(encoding="utf-8")
    version = re.escape(_package_version())

    assert re.search(rf"^## \[{version}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)
    assert re.search(rf"^\[{version}\]: {_REPOSITORY}/compare/", changelog, re.MULTILINE)


def test_changelog_keeps_an_unreleased_section_above_the_releases() -> None:
    headings = re.findall(r"^## \[([^\]]+)\]", _CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE)

    assert headings[:2] == ["Unreleased", _package_version()]


def test_testpypi_check_installs_only_the_package_from_testpypi() -> None:
    # PyPI has the old 0.1 line, and anyone can upload look-alike dependencies to TestPyPI: take
    # only environment-store from TestPyPI, pinned so that uv fails instead of falling back.
    contributing = _prose(_ROOT / "CONTRIBUTING.md")
    commands = [
        words
        for words in map(shlex.split, _CODE_SPAN.findall(contributing))
        if any(urlsplit(word).hostname == "test.pypi.org" for word in words)
    ]

    assert commands
    for words in commands:
        links = [
            words[index + 1] for index, word in enumerate(words[:-1]) if word == "--find-links"
        ]
        assert links == ["https://test.pypi.org/simple/environment-store/"]
        assert "environment-store[cli]==X.Y.Z" in words
        assert not any("-index" in word for word in words)


def test_readme_tells_0_1_users_to_uninstall_it_first() -> None:
    # With 0.1 installed, `pip install 'environment-store[cli]'` keeps 0.1 and installs no `envs`.
    readme = _prose(_ROOT / "README.md")
    note = readme[readme.index("Version 2.0 is a rewrite") :].split("\n\n", 1)[0]

    assert "uninstall it first" in note
    assert f"{_REPOSITORY}/blob/main/docs/installation.md" in note


def test_changelog_names_every_environment_variable_the_package_reads() -> None:
    read = {
        "ENV_STORE_KEY_" if name.startswith("ENV_STORE_KEY_") else name
        for source in (_ROOT / "src").rglob("*.py")
        for name in re.findall(r"ENV_STORE_[A-Z_]+", source.read_text(encoding="utf-8"))
    }
    changelog = _CHANGELOG.read_text(encoding="utf-8")

    assert read
    assert sorted(name for name in read if name not in changelog) == []


def _setting(*keys: str) -> object:
    """A value of pyproject.toml, e.g. `_setting("tool", "ruff", "target-version")`."""
    value: object = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for key in keys:
        assert isinstance(value, dict)
        value = value[key]
    return value


def _minimum_python() -> str:
    requires = _setting("project", "requires-python")
    assert isinstance(requires, str)
    match = re.fullmatch(r">=(3\.\d+)", requires)
    assert match
    return match.group(1)


# "Python 3.12 or newer", "**Python 3.12 or newer**", "Python 3.12+", "python3.12 -m venv".
_PYTHON_MINIMUM: Final = re.compile(
    r"[Pp]ython\**\s?(3\.\d+)(?:\+| or newer)|python(3\.\d+) -m venv"
)


@pytest.mark.parametrize(
    "document", [*_DOCUMENTS, _MAN_PAGE, _ROOT / "CONTRIBUTING.md"], ids=_document_id
)
def test_every_documented_minimum_python_is_requires_python(document: Path) -> None:
    found = {a or b for a, b in _PYTHON_MINIMUM.findall(document.read_text(encoding="utf-8"))}
    assert found <= {_minimum_python()}


def test_the_changelog_entry_of_the_version_names_the_minimum_python() -> None:
    changelog = _CHANGELOG.read_text(encoding="utf-8")
    entry = changelog.split(f"## [{_package_version()}]", 1)[1].split("\n## [", 1)[0]
    assert f"Python {_minimum_python()} or newer" in entry


def test_the_tools_and_classifiers_start_at_the_minimum_python() -> None:
    minimum = _minimum_python()
    classifiers = _setting("project", "classifiers")
    assert isinstance(classifiers, list)
    assert f"Programming Language :: Python :: {minimum}" in classifiers
    assert _setting("tool", "ruff", "target-version") == "py" + minimum.replace(".", "")
    assert _setting("tool", "ty", "environment", "python-version") == minimum


def test_ci_tests_the_minimum_python() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = re.search(r"^\s*python: \[(.*)\]$", ci, re.MULTILINE)
    assert matrix
    assert f'"{_minimum_python()}"' in matrix.group(1).split(", ")
