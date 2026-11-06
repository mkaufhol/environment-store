"""Output helpers: data on stdout, diagnostics on stderr (D33, spec §6).

Data is written to stdout as UTF-8 bytes, so values reach pipes exactly (no locale encoding, no
newline translation). Diagnostics are text lines on stderr. Prompts never use these helpers;
they go through the prompter, also on stderr (PD 20).
"""

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Final

import typer

from environment_store.core.errors import BackendError

__all__ = ["JsonValue", "display_value", "emit_json", "err", "out", "table", "write_value"]

type JsonValue = bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None
"""A value `emit_json` can write."""

_COLUMN_GAP: Final = "  "


def out(text: str = "", *, newline: bool = True) -> None:
    """Write data to stdout as UTF-8, byte-exact.

    Args:
        text: The text.
        newline: Whether to end it with a newline.

    Raises:
        BackendError: stdout is closed.
    """
    if sys.stdout is None:
        # Descriptor 1 is closed: typer.echo would drop the data silently and exit 0.
        message = "cannot write the output: stdout is closed"
        raise BackendError(message)
    data = text + "\n" if newline else text
    # Bytes go straight to the binary stream: no locale encoding, no newline translation.
    typer.echo(data.encode("utf-8"), nl=False)


def err(text: str) -> None:
    """Write one diagnostic line to stderr, e.g. `created store 'x'`.

    Args:
        text: The line without its newline.
    """
    typer.echo(text, err=True)


def emit_json(data: JsonValue) -> None:
    """Write exactly one JSON document to stdout, keys sorted, with a trailing newline.

    Args:
        data: The document.
    """
    out(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2))


def table(rows: Sequence[Sequence[str]]) -> str:
    """Format rows as aligned columns separated by two spaces.

    Args:
        rows: The rows; all of the same length.

    Returns:
        The lines joined by newlines, without a trailing newline or trailing blanks.
    """
    if not rows:
        return ""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    lines = (
        _COLUMN_GAP.join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in rows
    )
    return "\n".join(line.rstrip() for line in lines)


def display_value(value: str) -> str:
    """Return a value for line-oriented listings such as `ls -v`.

    Args:
        value: The value.

    Returns:
        The value itself if it is printable on one line, otherwise its JSON string form, so
        that a listing keeps one variable per line.
    """
    if value.isprintable():
        return value
    return json.dumps(value, ensure_ascii=False)


def write_value(value: str, *, tty: bool) -> None:
    """Write a raw value to stdout, as `get` prints it (D33, spec §6.7).

    Args:
        value: The value, written byte-exact.
        tty: Whether stdout is a terminal; only then a newline is added.

    Raises:
        BackendError: stdout is closed.
    """
    out(value, newline=tty)
