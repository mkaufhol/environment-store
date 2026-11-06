"""The dotenv reader: python-dotenv's syntax without interpolation, strict about errors."""

import io
import re
from typing import Final

import pytest
from dotenv import dotenv_values
from dotenv.parser import parse_stream
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.formats.dotenv import loads

_KEY: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_]+")

_CORPUS: Final[tuple[str, ...]] = (
    "",
    "\n\n",
    "A=1",
    "A=1\nB=2\n",
    "A=1\r\nB=2\r\n",
    "A=1\rB=2\r",
    "export A=1",
    "export\tA=1",
    "export=1",
    "  A  =  spaced value  ",
    "A=",
    "A=\nB=2",
    "A= # only a comment",
    "A=#not a comment",
    "A=value # comment",
    "A=value#hash",
    "A=value\t#tab comment",
    "# comment\nA=1\n  # indented comment",
    "A='single # quoted' # comment",
    'A="double # quoted"   ',
    "A='it\\'s'",
    "A='back\\\\slash'",
    "A='keep\\n'",
    'A="esc \\\\ \\" \\\' \\a \\b \\f \\n \\r \\t \\v"',
    'A="keep \\x41 \\u00e4 \\$"',
    "A='multi\nline'",
    'A="multi\nline"',
    "A='${NOT_INTERPOLATED}'",
    "A=${NOT_INTERPOLATED}",
    "A=1\nA=2",
    "'QUOTED_KEY'=v",
    "A=unicode äöü",
    "A=a\u2028b",
    "\u00a0A=1",
    "A=x\u00a0",
)


def _reference(text: str) -> dict[str, str | None]:
    return dict(dotenv_values(stream=io.StringIO(text), interpolate=False))


@pytest.mark.parametrize("text", _CORPUS)
def test_loads_matches_python_dotenv_without_interpolation(text: str) -> None:
    assert loads(text) == _reference(text)


def test_loads_does_not_interpolate_the_environment() -> None:
    assert loads('A=${HOME}\nB="${HOME}"\n') == {"A": "${HOME}", "B": "${HOME}"}


def test_loads_keeps_the_last_of_duplicate_variables() -> None:
    assert loads("A=1\nB=2\nA=3\n") == {"A": "3", "B": "2"}


@pytest.mark.parametrize(
    ("text", "line", "problem"),
    [
        ("A=1\nB", 2, "no value"),
        ("A=1\n\nB # comment", 3, "no value"),
        ("A=1\n=2", 2, "variable name"),
        ("A=1\n'=2", 2, "variable name"),
        ("A='unterminated", 1, "unterminated"),
        ('A=1\nB="unterminated\nC=3', 2, "unterminated"),
        ("A=1\r\nB='x' trailing", 2, "after the value"),
        ("A=1\rB='x'y", 2, "after the value"),
    ],
)
def test_loads_refuses_malformed_statements_naming_the_line(
    text: str, line: int, problem: str
) -> None:
    with pytest.raises(ValidationError, match=rf"line {line}\b.*{problem}"):
        loads(text)


@pytest.mark.parametrize("text", ["A-B=1", "A.B=1", "Ä=1", "'A B'=1"])
def test_loads_refuses_invalid_names(text: str) -> None:
    with pytest.raises(ValidationError, match=r"line 1.*invalid variable name"):
        loads(text)


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("KEY=-----BEGIN\nMIIsecretBASE64\n", 2),
        ("KEY=x\nab+/cdSECRET==\n", 2),
        ("API_KEY:sk_live_SECRET\n", 1),
        ("sk_live_SECRET/abc\n", 1),
    ],
)
def test_loads_refuses_malformed_lines_without_echoing_their_text(text: str, line: int) -> None:
    with pytest.raises(ValidationError, match=rf"line {line}\b") as excinfo:
        loads(text)

    assert "secret" not in str(excinfo.value).lower()


def test_loads_accepts_nested_keys_of_stores_starting_with_a_digit() -> None:
    assert loads("9LIVES__X=v") == {"9LIVES__X": "v"}


def test_loads_refuses_nul_without_echoing_the_value() -> None:
    with pytest.raises(ValidationError, match="NUL") as excinfo:
        loads("TOKEN=sec\x00ret")

    assert "sec" not in str(excinfo.value)


def test_loads_refuses_lone_surrogates() -> None:
    with pytest.raises(ValidationError, match="surrogate"):
        loads("A=\ud800")


def _python_dotenv_accepts(text: str) -> bool:
    bindings = list(parse_stream(io.StringIO(text)))
    return all(
        not binding.error
        and (binding.key is None or (_KEY.fullmatch(binding.key) and binding.value is not None))
        for binding in bindings
    )


_DOTENV_ALPHABET: Final[st.SearchStrategy[str]] = st.sampled_from(
    [*"AB_9=#'\"\\ \t\n\r$x{}", "export ", "\u00a0", "\u2028", "\x0b", "ä", "\\n", "\\'"]
)


@given(st.lists(_DOTENV_ALPHABET, max_size=30).map("".join))
def test_loads_agrees_with_python_dotenv_or_refuses_what_it_skips(text: str) -> None:
    if _python_dotenv_accepts(text):
        assert loads(text) == _reference(text)
    else:
        with pytest.raises(ValidationError, match="line"):
            loads(text)
