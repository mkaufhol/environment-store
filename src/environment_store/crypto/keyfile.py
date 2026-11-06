"""Key files and passphrase files (spec §4.2, §4.3, D3, D4).

A key file is one line of text: `envstore-key-v1:` followed by the unpadded URL-safe base64 form
of 32 random bytes. The prefix lets the tool reject a file that is not a key file, e.g. a
passphrase file passed for a `keyfile` store, with a clear error. Error messages never contain
the file content.
"""

import base64
import os
import re
import secrets
from pathlib import Path
from typing import Final

from environment_store.core.errors import BackendError, InvalidKeyFileError, ValidationError
from environment_store.core.secrets import KEY_LENGTH, KeyMaterial, Passphrase

__all__ = [
    "KEY_FILE_PREFIX",
    "format_key",
    "generate_key",
    "looks_like_key_file",
    "parse_key",
    "passphrase_from_text",
    "read_key_file",
    "read_passphrase_file",
    "write_key_file",
]

KEY_FILE_PREFIX: Final[str] = "envstore-key-v1:"
"""First characters of every key file; names the format version."""

# 32 bytes are 43 base64 characters without padding.
_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"{re.escape(KEY_FILE_PREFIX)}(?P<body>[A-Za-z0-9_-]{{43}})"
)
_KEY_FILE_MODE: Final[int] = 0o600
_INVALID_KEY_MESSAGE: Final[str] = (
    f"not a valid key file: expected one line '{KEY_FILE_PREFIX}<base64url of 32 bytes>' "
    "(create one with keygen)"
)


def generate_key() -> KeyMaterial:
    """Generate a new random key.

    Returns:
        32 bytes from the operating system's secure random source.
    """
    return KeyMaterial(key=secrets.token_bytes(KEY_LENGTH))


def format_key(key: KeyMaterial) -> str:
    """Return the key file text of a key.

    Args:
        key: The key.

    Returns:
        `envstore-key-v1:<unpadded base64url>` followed by a newline.
    """
    body = base64.urlsafe_b64encode(key.key).decode("ascii").rstrip("=")
    return f"{KEY_FILE_PREFIX}{body}\n"


def parse_key(text: str) -> KeyMaterial:
    """Parse the text of a key file.

    Surrounding whitespace (e.g. the trailing newline) is ignored. Only the canonical encoding
    is accepted, so every key has exactly one key file text.

    Args:
        text: The key file text.

    Returns:
        The key.

    Raises:
        InvalidKeyFileError: The text is not a key file; the message never contains the text.
    """
    match = _KEY_PATTERN.fullmatch(text.strip())
    if match is None:
        raise InvalidKeyFileError(_INVALID_KEY_MESSAGE)
    body = match.group("body")
    raw = base64.urlsafe_b64decode(body + "=")
    key = KeyMaterial(key=raw)
    if format_key(key).rstrip("\n") != match.group(0):
        # Non-zero padding bits: a second spelling of the same key, refused to stay canonical.
        raise InvalidKeyFileError(_INVALID_KEY_MESSAGE)
    return key


def looks_like_key_file(text: str) -> bool:
    """Tell whether text is meant as a key file, valid or not.

    Used to refuse a key file given for a `passphrase` store (D3).

    Args:
        text: Raw secret text.

    Returns:
        Whether the text, without leading whitespace, starts with the key file prefix.
    """
    return text.lstrip().startswith(KEY_FILE_PREFIX)


def read_key_file(path: Path) -> KeyMaterial:
    """Read and parse a key file.

    Args:
        path: The key file.

    Returns:
        The key.

    Raises:
        BackendError: The file cannot be read.
        InvalidKeyFileError: The file is not a key file.
    """
    data = _read_bytes(path, what="key file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Not chained: the decode error holds the raw file content, which may be secret.
        raise InvalidKeyFileError(_INVALID_KEY_MESSAGE) from None
    return parse_key(text)


def write_key_file(path: Path, key: KeyMaterial) -> None:
    """Write a new key file with mode `0600`; never overwrites (D4).

    The file is created with `O_CREAT | O_EXCL`, which fails on any existing path, symlinks
    included, so nothing is ever replaced or followed. A partially written file is removed.

    Args:
        path: Where to create the key file.
        key: The key.

    Raises:
        ValidationError: The path exists already.
        BackendError: The file cannot be created or written.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, _KEY_FILE_MODE)
    except FileExistsError as err:
        message = f"key file '{path}' already exists; refusing to overwrite it"
        raise ValidationError(message) from err
    except OSError as err:
        message = f"cannot write key file '{path}': {err.strerror}"
        raise BackendError(message) from err
    try:
        # The umask may have removed bits only; make the mode exact.
        os.fchmod(fd, _KEY_FILE_MODE)
        with os.fdopen(fd, "wb", closefd=False) as file:
            file.write(format_key(key).encode("ascii"))
            file.flush()
            os.fsync(fd)
    except OSError as err:
        os.close(fd)
        path.unlink(missing_ok=True)
        message = f"cannot write key file '{path}': {err.strerror}"
        raise BackendError(message) from err
    os.close(fd)


def passphrase_from_text(text: str) -> Passphrase:
    """Turn raw passphrase text from a file or stdin into a passphrase (D3).

    Exactly one trailing line break (LF or CRLF) is stripped; everything else is kept.

    Args:
        text: The raw text.

    Returns:
        The passphrase.

    Raises:
        ValidationError: The passphrase is empty.
    """
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    return Passphrase(text=text)


def read_passphrase_file(path: Path) -> Passphrase:
    """Read a passphrase file; one trailing newline is stripped (D3).

    Args:
        path: The passphrase file, UTF-8.

    Returns:
        The passphrase.

    Raises:
        BackendError: The file cannot be read.
        ValidationError: The file is not UTF-8 or the passphrase is empty.
    """
    data = _read_bytes(path, what="passphrase file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        message = f"passphrase file '{path}' is not valid UTF-8"
        # Not chained: the decode error holds the raw passphrase.
        raise ValidationError(message) from None
    return passphrase_from_text(text)


def _read_bytes(path: Path, *, what: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as err:
        message = f"cannot read {what} '{path}': {err.strerror}"
        raise BackendError(message) from err
