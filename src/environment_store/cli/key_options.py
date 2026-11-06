r"""`-k` parsing (D3, D16, D33, PD 19).

Reading commands bind keys by store name: `-k store=path` or `-k store=-`; a bare path or `-` is
the shorthand for a single store. A value is `store=path` when the text before the first `=`
is a valid store name, otherwise it is a bare path, so `./a=b.key` and `C:\\keys\\a.key` stay
paths. Writing commands act on one store (`-s`) and take a bare path or `-` only.

A leading `~` is expanded like the TUI's unlock dialog and the project file's `[keys]` do: the
shell leaves it literal after `store=` (zsh) and inside quotes.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from environment_store.config.secrets import KeyFile, KeySource, KeyStdin
from environment_store.core.errors import KeySourceError, ValidationError
from environment_store.core.validation import STORE_NAME_PATTERN

__all__ = ["parse_key_path", "parse_reading_keys", "parse_writing_key"]

_STDIN: Final = "-"
_HOME: Final = "~"


def parse_reading_keys(values: Sequence[str], stores: Sequence[str]) -> dict[str, KeySource]:
    """Parse the `-k` values of a reading command.

    Args:
        values: The `-k` values in the order given.
        stores: The effective store list (validated names, load order).

    Returns:
        Store name → key source.

    Raises:
        ValidationError: A key for a store not in the list, two keys for one store, an empty
            path, the shorthand with several stores, or more than one `-` (stdin is read
            once, D3).
    """
    sources: dict[str, KeySource] = {}
    for value in values:
        store, path = _split(value, stores)
        if store not in stores:
            message = f"-k names store {store!r}, which is not in the store list"
            raise ValidationError(message)
        if store in sources:
            message = f"more than one -k for store {store!r}"
            raise ValidationError(message)
        sources[store] = parse_key_path(path)
    if sum(isinstance(source, KeyStdin) for source in sources.values()) > 1:
        message = "only one -k may read from stdin ('-'); stdin can be read once"
        raise ValidationError(message)
    return sources


def parse_writing_key(value: str | None) -> KeySource | None:
    """Parse the `-k` value of a writing command (a path or `-`).

    Args:
        value: The `-k` value, or `None` if not given.

    Returns:
        The key source, or `None`.

    Raises:
        ValidationError: The path is empty.
    """
    return None if value is None else parse_key_path(value)


def _split(value: str, stores: Sequence[str]) -> tuple[str, str]:
    name, separator, path = value.partition("=")
    if separator and STORE_NAME_PATTERN.fullmatch(name):
        return name, path
    distinct = tuple(dict.fromkeys(stores))
    if len(distinct) != 1:
        message = (
            "-k <path> without a store name works with exactly one store; with several "
            "stores bind each key by name: -k <store>=<path>"
        )
        raise ValidationError(message)
    return distinct[0], value


def parse_key_path(path: str, *, option: str = "-k") -> KeySource:
    """Parse a key path given on the command line: a file, or `-` for stdin.

    Args:
        path: The path text.
        option: The option the path was given with, for messages.

    Returns:
        The key source.

    Raises:
        ValidationError: The path is empty.
        KeySourceError: The path starts with `~user` for an unknown user.
    """
    if not path:
        message = f"the path of {option} is empty; give a key file path or '-' for stdin"
        raise ValidationError(message)
    if path == _STDIN:
        return KeyStdin()
    if not path.startswith(_HOME):
        # Checked on the text: Path drops a leading "./", so Path("./~/a") is Path("~/a").
        return KeyFile(Path(path))
    try:
        return KeyFile(Path(path).expanduser())
    except RuntimeError as error:
        message = f"key file path '{path}' names an unknown home directory"
        raise KeySourceError(message) from error
