"""The dotenv writer (D37), verified against python-dotenv.

Docker Compose cannot run in the tests; its documented semantics (single quotes literal,
`$VAR` / `${VAR}` interpolated in unquoted and double-quoted values, `\\`, `\"`, `\n`, `\r`,
`\t` escapes in double quotes) are the reason for the `$` refusals tested here.
"""

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest
from dotenv import dotenv_values
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.formats.dotenv import dumps, loads
from tests.support.strategies import values, variable_maps, variable_names

# value -> the exact line the writer produces for variable A.
_GOLDEN: Final[tuple[tuple[str, str], ...]] = (
    ("localhost", "A=localhost"),
    ("a/b:c@d%e+f,g-h_i.J9", "A=a/b:c@d%e+f,g-h_i.J9"),
    ("", "A=''"),
    ("hello world", "A='hello world'"),
    ("$HOME and $(id)", "A='$HOME and $(id)'"),
    ("$", "A='$'"),
    ("{x}$", "A='{x}$'"),
    ('"double"', "A='\"double\"'"),
    ("#not a comment", "A='#not a comment'"),
    ("a #b", "A='a #b'"),
    ("  padded  ", "A='  padded  '"),
    ("\ttab", "A='\ttab'"),
    ("a=b=c", "A='a=b=c'"),
    ("unicode äöü ✓ 😀", "A='unicode äöü ✓ 😀'"),
    ("\x0bvt\x0cff\x85nel\u2028ls", "A='\x0bvt\x0cff\x85nel\u2028ls'"),
    ("it's", 'A="it\'s"'),
    ("line1\nline2", 'A="line1\\nline2"'),
    ("line1\r\nline2\n", 'A="line1\\r\\nline2\\n"'),
    ("cr\ronly", 'A="cr\\ronly"'),
    ("back\\slash", 'A="back\\\\slash"'),
    ("trailing\\", 'A="trailing\\\\"'),
    ("\\'", 'A="\\\\\'"'),
    ("\\n literal", 'A="\\\\n literal"'),
    ('say "hi"\n\tbye', 'A="say \\"hi\\"\\n\\tbye"'),
    (
        "-----BEGIN KEY-----\nabc==\n-----END KEY-----\n",
        'A="-----BEGIN KEY-----\\nabc==\\n-----END KEY-----\\n"',
    ),
)


def _python_dotenv(text: str) -> dict[str, str | None]:
    return dict(dotenv_values(stream=io.StringIO(text)))


@pytest.mark.parametrize(("value", "line"), _GOLDEN)
def test_dumps_quotes_values_by_the_d37_rules(value: str, line: str) -> None:
    assert dumps({"A": value}) == f"{line}\n"


@pytest.mark.parametrize(("value", "line"), _GOLDEN)
def test_python_dotenv_reads_every_golden_line_back_exactly(value: str, line: str) -> None:
    assert _python_dotenv(f"{line}\n") == {"A": value}


@pytest.mark.parametrize(("value", "line"), _GOLDEN)
def test_loads_reads_every_golden_line_back_exactly(value: str, line: str) -> None:
    assert loads(f"{line}\n") == {"A": value}


def test_python_dotenv_reads_the_golden_lines_back_from_a_file(tmp_path: Path) -> None:
    variables = {f"V{index}": value for index, (value, _) in enumerate(_GOLDEN)}
    path = tmp_path / ".env"
    path.write_text(dumps(variables), encoding="utf-8")

    assert dotenv_values(path, encoding="utf-8") == variables


def test_dumps_writes_one_line_per_variable_in_input_order() -> None:
    assert dumps({"B": "2", "A": "1"}) == "B=2\nA=1\n"


def test_dumps_of_nothing_is_empty() -> None:
    assert dumps({}) == ""


def test_dumps_accepts_nested_keys_of_stores_starting_with_a_digit() -> None:
    assert dumps({"9LIVES__X": "v"}) == "9LIVES__X=v\n"


@pytest.mark.parametrize("name", ["", "A-B", "A B", "A=B", "#A", "Ä", "A\n"])
def test_dumps_refuses_names_dotenv_cannot_hold(name: str) -> None:
    with pytest.raises(ValidationError, match="dotenv"):
        dumps({name: "v"})


def test_dumps_refuses_nul_without_echoing_the_value() -> None:
    with pytest.raises(ValidationError, match="NUL") as excinfo:
        dumps({"A": "sec\x00ret"})

    assert "sec" not in str(excinfo.value)


@pytest.mark.parametrize(
    "value", ["it's $5", "a\nb$c", "C:\\$x", "multi\nline $HOME", "cr\r$", "x$'s"]
)
def test_dumps_refuses_values_needing_double_quotes_that_contain_a_dollar(value: str) -> None:
    with pytest.raises(ValidationError, match=r"'TOKEN'.*double quotes.*\$") as excinfo:
        dumps({"TOKEN": value})

    message = str(excinfo.value)
    assert all(hint in message for hint in ("-t json", "-t toml", "envs run"))
    assert value not in message


@pytest.mark.parametrize("value", ["${HOME}", "pre${X:-d}post", "${", "a${b"])
def test_dumps_refuses_values_containing_dollar_brace(value: str) -> None:
    # python-dotenv interpolates `${…}` in every quoting style, single quotes included.
    with pytest.raises(ValidationError, match=r"'TOKEN'.*\$\{") as excinfo:
        dumps({"TOKEN": value})

    assert all(hint in str(excinfo.value) for hint in ("-t json", "-t toml", "envs run"))


def test_python_dotenv_interpolates_dollar_brace_even_in_single_quotes() -> None:
    # The measured behaviour behind the `${` refusal (python-dotenv 1.2).
    assert _python_dotenv("A='${UNSET_FOR_SURE_42}'\n") == {"A": ""}


def _representable(value: str) -> bool:
    return "$" not in value


def _dotenv_keys() -> st.SearchStrategy[str]:
    return st.one_of(variable_names(), st.from_regex(r"[0-9][A-Za-z0-9_]*", fullmatch=True))


@given(st.dictionaries(_dotenv_keys(), values().filter(_representable), max_size=8))
def test_values_without_dollar_round_trip_through_loads_and_python_dotenv(
    variables: dict[str, str],
) -> None:
    text = dumps(variables)

    assert loads(text) == variables
    assert _python_dotenv(text) == variables


@given(variable_maps())
def test_dumps_either_refuses_or_round_trips_exactly(variables: Mapping[str, str]) -> None:
    try:
        text = dumps(variables)
    except ValidationError:
        assert any("$" in value for value in variables.values())
        return

    assert loads(text) == variables
    assert _python_dotenv(text) == variables


_SINGLE_QUOTE_BREAKERS: Final[dict[int, int | None]] = str.maketrans("", "", "'\\\r\n")


@given(
    values()
    .map(lambda value: value.translate(_SINGLE_QUOTE_BREAKERS))
    .filter(lambda value: "${" not in value)
)
def test_single_line_values_without_quote_or_backslash_keep_their_dollars(value: str) -> None:
    text = dumps({"A": value})

    assert loads(text) == {"A": value}
    assert _python_dotenv(text) == {"A": value}
