"""`envs keygen`: write a new random key file, or print the key (spec §4.5, D4, D33).

`keygen` opens no store, so it needs no connection (PD 17); like every command it still fails
on a broken configuration (PD 10).
"""

from pathlib import Path
from typing import Annotated, Final

import typer

from environment_store.cli.output import err, out
from environment_store.core.errors import ValidationError
from environment_store.library.keys import generate_key_file, generate_key_text

__all__ = ["keygen"]

_STDOUT: Final = "-"

KeyPathArg = Annotated[
    str,
    typer.Argument(
        metavar="PATH|-",
        help="Where to create the key file (mode 0600, never overwritten); '-' prints the key.",
        show_default=False,
    ),
]


def keygen(path: KeyPathArg) -> None:
    """Generate a random key file.

    'envs keygen -' prints the key instead, e.g. for a password manager.
    """
    if path == _STDOUT:
        out(generate_key_text(), newline=False)
        return
    if not path:
        # Path("") is Path("."): the refusal would name a directory the user never typed.
        message = "keygen needs a file path, or '-' to print the key"
        raise ValidationError(message)
    generate_key_file(Path(path))
    err(f"wrote key file '{path}'")
