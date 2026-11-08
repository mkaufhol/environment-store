"""The user documentation and the agent skill stay in sync with the CLI and with each other."""

import re
from pathlib import Path
from typing import Final

import pytest
from typer.main import get_command

from environment_store.cli._typer import EnvsGroup
from environment_store.cli.app import app
from environment_store.core.errors import MissingExtraError

_ROOT: Final = Path(__file__).parents[2]
_CLI_GUIDE: Final = _ROOT / "docs" / "cli.md"
_SKILL_DIR: Final = _ROOT / ".claude" / "skills" / "environment-store-cli"
_SKILL: Final = _SKILL_DIR / "SKILL.md"
_DOCUMENTS: Final = (
    _ROOT / "README.md",
    *sorted((_ROOT / "docs").glob("*.md")),
    *sorted(_SKILL_DIR.glob("*.md")),
)

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


@pytest.mark.parametrize("document", _DOCUMENTS, ids=_document_id)
def test_relative_links_point_to_existing_files(document: Path) -> None:
    missing = [
        target
        for target in _relative_links(document)
        if target.partition("#")[0] and not (document.parent / target.partition("#")[0]).exists()
    ]

    assert missing == []


@pytest.mark.parametrize("document", _DOCUMENTS, ids=_document_id)
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
