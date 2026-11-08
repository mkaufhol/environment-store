"""Output helpers: data on stdout, diagnostics on stderr, JSON documents."""

import json
import sys

import pytest

from environment_store.cli.output import display_value, emit_json, err, out, table, write_value
from environment_store.core.errors import BackendError


def test_out_writes_a_line_to_stdout_only(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    out("hello wörld")

    captured = capsysbinary.readouterr()
    assert captured.out == "hello wörld\n".encode()
    assert captured.err == b""


def test_out_without_newline_writes_the_text_only(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    out("a", newline=False)

    assert capsysbinary.readouterr().out == b"a"


def test_out_without_text_writes_an_empty_line(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    out()

    assert capsysbinary.readouterr().out == b"\n"


def test_out_keeps_carriage_returns_exactly(capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    out("a\r\nb\r", newline=False)

    assert capsysbinary.readouterr().out == b"a\r\nb\r"


def test_err_writes_a_line_to_stderr_only(capsys: pytest.CaptureFixture[str]) -> None:
    err("created store 'x'")

    captured = capsys.readouterr()
    assert captured.err == "created store 'x'\n"
    assert captured.out == ""


def test_emit_json_writes_one_sorted_document_with_a_trailing_newline(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    emit_json([{"name": "ä", "b": True, "a": None}, {"n": 1}])

    text = capsysbinary.readouterr().out.decode()
    assert text.endswith("}\n]\n")
    assert json.loads(text) == [{"name": "ä", "b": True, "a": None}, {"n": 1}]
    assert "ä" in text
    assert text.index('"a"') < text.index('"b"') < text.index('"name"')


def test_table_aligns_columns_with_two_spaces_and_no_trailing_blanks() -> None:
    rows = [["name", "mode"], ["a_long_name", "plain"], ["b", "encrypted (keyfile)"]]

    assert table(rows) == (
        "name         mode\na_long_name  plain\nb            encrypted (keyfile)"
    )


def test_table_of_single_column_rows_is_one_value_per_line() -> None:
    assert table([["a"], ["bb"]]) == "a\nbb"


def test_table_of_no_rows_is_empty() -> None:
    assert table([]) == ""


@pytest.mark.parametrize(
    "value", ["plain", "with spaces", "ünïcode €", "", "a=b", "quotes \" and '"]
)
def test_display_value_shows_single_line_printable_values_as_they_are(value: str) -> None:
    assert display_value(value) == value


@pytest.mark.parametrize("value", ["two\nlines", "cr\r", "tab\there", "bell\a", "-----BEGIN\n"])
def test_display_value_shows_other_values_as_json_strings(value: str) -> None:
    shown = display_value(value)

    assert "\n" not in shown
    assert json.loads(shown) == value


def test_write_value_writes_the_raw_value_without_newline_when_piped(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    write_value("a\r\nb\n", tty=False)

    assert capsysbinary.readouterr().out == b"a\r\nb\n"


def test_write_value_adds_a_newline_on_a_terminal(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    write_value("secret", tty=True)

    assert capsysbinary.readouterr().out == b"secret\n"


def test_out_to_a_closed_stdout_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A closed descriptor 1 makes sys.stdout None; writing nothing must not pass as success.
    monkeypatch.setattr(sys, "stdout", None)

    with pytest.raises(BackendError, match="stdout is closed"):
        out("A=1")


def test_write_value_to_a_closed_stdout_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)

    with pytest.raises(BackendError, match="stdout is closed"):
        write_value("secret", tty=False)
