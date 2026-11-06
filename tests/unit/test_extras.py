"""The `all` extra is exactly the union of the other extras (PD 15)."""

import tomllib
from pathlib import Path
from typing import Final

_PYPROJECT: Final = Path(__file__).parents[2] / "pyproject.toml"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    return {str(name): [str(requirement) for requirement in extras[name]] for name in extras}


def test_all_extra_contains_every_requirement_of_the_other_extras_verbatim() -> None:
    extras = _extras()
    everything = set(extras.pop("all"))

    for name, requirements in extras.items():
        assert set(requirements) <= everything, name


def test_all_extra_contains_nothing_but_the_other_extras() -> None:
    extras = _extras()
    everything = extras.pop("all")

    assert sorted(everything) == sorted({req for reqs in extras.values() for req in reqs})


def test_cli_extra_requires_typer_with_vendored_click() -> None:
    assert _extras()["cli"] == ["typer>=0.26"]


def test_tui_extra_requires_the_tested_textual_line() -> None:
    # PD 15: the floor is the tested version line, not just any textual.
    assert _extras()["tui"] == ["textual>=8.2"]


def test_testing_group_installs_the_same_textual_line_as_the_tui_extra() -> None:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))

    assert "textual>=8.2" in data["dependency-groups"]["testing"]
