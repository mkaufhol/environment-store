"""Key generation for the public library (spec §4.5, D4)."""

import os
from pathlib import Path

from environment_store.crypto.keyfile import format_key, generate_key, write_key_file

__all__ = ["generate_key_file", "generate_key_text"]


def generate_key_file(path: Path | str | os.PathLike[str]) -> None:
    """Write a new random key file with mode `0600`; never overwrites (D4).

    Args:
        path: Where to create the key file.

    Raises:
        ValidationError: The path exists already.
        BackendError: The file cannot be written.
    """
    write_key_file(Path(path), generate_key())


def generate_key_text() -> str:
    """Return the key file text of a new random key, e.g. for a password manager.

    Returns:
        `envstore-key-v1:<base64url>` followed by a newline.
    """
    return format_key(generate_key())
