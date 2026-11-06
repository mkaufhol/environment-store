r"""dotenv import and export (spec §6.10, §6.11, D37).

**Writing** — every line is `KEY=VALUE`, quoted so that both python-dotenv and Docker Compose read
the value back exactly:

1. unquoted for non-empty values made only of `[A-Za-z0-9_./:@%+,-]`;
2. single quotes (literal in both tools, so `$` needs no escape) for values without `'`, `\`,
   newline or carriage return;
3. double quotes with `\\`, `\"`, `\n`, `\r`, `\t` escapes for all other values, as long as
   they contain no `$`;
4. a value that needs double quotes **and** contains `$` is refused: Compose interpolates `$` in
   double quotes and no escape works in both tools.

Measured against python-dotenv 1.2 (golden tests), two refinements of D37 keep it exact:
python-dotenv decodes `\\` and `\'` inside single quotes, so values with a backslash use double
quotes (rule 2); and it interpolates `${…}` in *every* quoting style, single quotes included, so
values containing `${` are refused as well.

**Reading** follows python-dotenv's syntax (optional `export`, comments, blank lines, single,
double and unquoted values, `\r\n` line ends) but never interpolates: `${X}` is imported
literally, so the importing process's environment never leaks into a store. Statements that
python-dotenv would skip with a warning are refused, naming the line.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NoReturn

from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_value

__all__ = ["KEY_PATTERN", "dumps", "loads"]

KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_]+")
"""dotenv keys: variable names, plus nested keys of stores starting with a digit (`9LIVES__X`)."""

_UNQUOTED: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_./:@%+,-]+")
_NEEDS_DOUBLE_QUOTES: Final[frozenset[str]] = frozenset("'\\\n\r")
_WRITE_ESCAPES: Final[Mapping[str, str]] = MappingProxyType(
    {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
)
_REFUSAL_HINT: Final[str] = "export with -t json or -t toml, or use envs run instead"

# python-dotenv's grammar (dotenv/parser.py), so that both read the same files the same way.
_MULTILINE_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s*")
_EXPORT: Final[re.Pattern[str]] = re.compile(r"(?:export[^\S\r\n]+)?")
_SINGLE_QUOTED_KEY: Final[re.Pattern[str]] = re.compile(r"'([^']+)'")
_UNQUOTED_KEY: Final[re.Pattern[str]] = re.compile(r"([^=\#\s]+)")
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"[^\S\r\n]*")
_EQUAL_SIGN: Final[re.Pattern[str]] = re.compile(r"=[^\S\r\n]*")
_SINGLE_QUOTED_VALUE: Final[re.Pattern[str]] = re.compile(r"'((?:\\.|[^'\\])*)'", re.DOTALL)
_DOUBLE_QUOTED_VALUE: Final[re.Pattern[str]] = re.compile(r'"((?:\\.|[^"\\])*)"', re.DOTALL)
_UNQUOTED_VALUE: Final[re.Pattern[str]] = re.compile(r"[^\r\n]*")
_INLINE_COMMENT: Final[re.Pattern[str]] = re.compile(r"\s+#.*")
_COMMENT: Final[re.Pattern[str]] = re.compile(r"(?:[^\S\r\n]*#[^\r\n]*)?")
_END_OF_LINE: Final[re.Pattern[str]] = re.compile(r"[^\S\r\n]*(?:\r\n|\n|\r|$)")
_LINE_BREAK: Final[re.Pattern[str]] = re.compile(r"\r\n|\n|\r")
_SINGLE_QUOTE_ESCAPES: Final[re.Pattern[str]] = re.compile(r"\\[\\']")
_DOUBLE_QUOTE_ESCAPES: Final[re.Pattern[str]] = re.compile(r"\\[\\'\"abfnrtv]")
_READ_ESCAPES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "\\": "\\",
        "'": "'",
        '"': '"',
        "a": "\a",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "v": "\v",
    }
)


def dumps(variables: Mapping[str, str]) -> str:
    """Serialize variables as dotenv lines (D37).

    Args:
        variables: Keys and values, in output order. Keys match `KEY_PATTERN`.

    Returns:
        One `KEY=VALUE` line per variable, each ending with a newline; empty for no variables.

    Raises:
        ValidationError: A key does not match `KEY_PATTERN`, a value contains NUL, or a value
            cannot be written so that python-dotenv and Docker Compose both read it back
            exactly. Values are never echoed.
    """
    return "".join(f"{_key(name)}={_quote(name, value)}\n" for name, value in variables.items())


def _key(name: str) -> str:
    if not KEY_PATTERN.fullmatch(name):
        message = (
            f"{name!r} cannot be written as a dotenv key: use letters, digits and '_' "
            f"({KEY_PATTERN.pattern})"
        )
        raise ValidationError(message)
    return name


def _quote(name: str, value: str) -> str:
    validate_value(value, variable=name)
    if "${" in value:
        _refuse(name, "contains '${', which python-dotenv interpolates even in single quotes")
    if _UNQUOTED.fullmatch(value):
        return value
    if _NEEDS_DOUBLE_QUOTES.isdisjoint(value):
        return f"'{value}'"
    if "$" in value:
        _refuse(
            name,
            "needs double quotes (it contains a newline, carriage return, ' or \\) and contains "
            "'$', which Docker Compose interpolates in double quotes",
        )
    return '"' + "".join(_WRITE_ESCAPES.get(char, char) for char in value) + '"'


def _refuse(name: str, reason: str) -> NoReturn:
    message = (
        f"the value of {name!r} cannot be written to a dotenv file that python-dotenv and "
        f"Docker Compose both read back exactly: it {reason}; {_REFUSAL_HINT}"
    )
    raise ValidationError(message)


def loads(text: str) -> dict[str, str]:
    """Parse dotenv text without interpolation.

    Args:
        text: The dotenv text.

    Returns:
        The variables in order of first appearance; a repeated key keeps its last value.

    Raises:
        ValidationError: A statement is malformed (no `=`, unterminated quotes, text after a
            quoted value), a key does not match `KEY_PATTERN`, or a value contains NUL or a lone
            surrogate. The message names the line but never echoes a value.
    """
    return _Parser(text).parse()


class _Parser:
    """A cursor over dotenv text, mirroring python-dotenv's `parse_binding`."""

    __slots__ = ("_position", "_start", "_text")

    def __init__(self, text: str) -> None:
        self._text: str = text
        self._position: int = 0
        self._start: int = 0

    def parse(self) -> dict[str, str]:
        variables: dict[str, str] = {}
        while self._position < len(self._text):
            self._match(_MULTILINE_WHITESPACE)
            if self._position == len(self._text):
                break
            self._start = self._position
            binding = self._binding()
            if binding is not None:
                name, value = binding
                variables[name] = value
        return variables

    def _binding(self) -> tuple[str, str] | None:
        self._match(_EXPORT)
        name = self._name()
        self._match(_WHITESPACE)
        value = self._assignment()
        self._match(_COMMENT)
        self._expect(_END_OF_LINE, "unexpected text after the value")
        if name is None:
            return None
        if value is None:
            self._fail("the statement has no value; expected NAME=VALUE (no '=' found)")
        try:
            validate_value(value, variable=name)
        except ValidationError as err:
            self._fail(str(err))
        return name, value

    def _name(self) -> str | None:
        first = self._peek()
        if first == "#":
            return None
        pattern = _SINGLE_QUOTED_KEY if first == "'" else _UNQUOTED_KEY
        name = self._expect(pattern, "expected a variable name").group(1)
        if not KEY_PATTERN.fullmatch(name):
            # The text is not echoed: on a malformed line it is often value material, such as
            # the continuation of an unquoted multi-line value or `KEY:secret`.
            self._fail(
                f"invalid variable name: use letters, digits and '_' ({KEY_PATTERN.pattern})"
            )
        return name

    def _assignment(self) -> str | None:
        if self._peek() != "=":
            return None
        equal_sign = self._match(_EQUAL_SIGN)
        # `KEY= # comment` is empty, while `KEY=#x` is the value `#x` (python-dotenv).
        if len(equal_sign) > 1 and self._peek() == "#":
            return ""
        return self._value()

    def _value(self) -> str:
        first = self._peek()
        if first == "'":
            raw = self._expect(_SINGLE_QUOTED_VALUE, "unterminated single-quoted value").group(1)
            return _decode(_SINGLE_QUOTE_ESCAPES, raw)
        if first == '"':
            raw = self._expect(_DOUBLE_QUOTED_VALUE, "unterminated double-quoted value").group(1)
            return _decode(_DOUBLE_QUOTE_ESCAPES, raw)
        return _INLINE_COMMENT.sub("", self._match(_UNQUOTED_VALUE)).rstrip()

    def _peek(self) -> str:
        return self._text[self._position : self._position + 1]

    def _match(self, pattern: re.Pattern[str]) -> str:
        """Consume a pattern that always matches (it may match the empty string)."""
        return self._expect(pattern, "internal parser error").group(0)

    def _expect(self, pattern: re.Pattern[str], problem: str) -> re.Match[str]:
        match = pattern.match(self._text, self._position)
        if match is None:
            self._fail(problem)
        self._position = match.end()
        return match

    def _fail(self, problem: str) -> NoReturn:
        line = len(_LINE_BREAK.findall(self._text, 0, self._start)) + 1
        message = f"invalid dotenv input at line {line}: {problem}"
        raise ValidationError(message)


def _decode(escapes: re.Pattern[str], raw: str) -> str:
    return escapes.sub(lambda match: _READ_ESCAPES[match.group(0)[1]], raw)
