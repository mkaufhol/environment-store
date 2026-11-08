"""Key generation and key text for the public library."""

import os
from pathlib import Path

from environment_store.core.secrets import KeyMaterial
from environment_store.crypto.keyfile import format_key, generate_key, parse_key, write_key_file

__all__ = ["generate_key_file", "generate_key_text", "parse_key_text"]


def generate_key_file(path: Path | str | os.PathLike[str]) -> None:
    """Write a new random key file with mode `0600`; never overwrites.

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


def parse_key_text(text: str) -> KeyMaterial:
    """Parse key text (`envstore-key-v1:...`) without a file, e.g. from a secret manager.

    The result is a key wherever the library takes one: `key=` of `EnvironmentStore` methods,
    `Source(..., key=...)` and `load(keys={...})`.

    Example:
        ```python
        import os

        from environment_store import load, parse_key_text

        load("prod", keys={"prod": parse_key_text(os.environ["PROD_STORE_KEY"])})
        ```

    Args:
        text: The key text, as `generate_key_text()` returns it or a key file holds it;
            surrounding whitespace such as the trailing newline is ignored.

    Returns:
        The key.

    Raises:
        InvalidKeyFileError: The text is not key text; the message never contains it.
    """
    return parse_key(text)
