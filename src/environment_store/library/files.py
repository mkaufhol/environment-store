"""Output and input files of exports and imports.

Output files hold decrypted secrets: they are created with mode `0600`, never replaced unless
asked, replaced atomically when asked, and never left behind half-written.
"""

import os
import tempfile
from pathlib import Path
from typing import Final

from environment_store.core.errors import BackendError, ValidationError

__all__ = ["OutputFileExistsError", "read_input_file", "write_output_file"]

_MODE: Final = 0o600


class OutputFileExistsError(ValidationError):
    """The output file exists and replacing it was not requested.

    Attributes:
        path: The output file.
    """

    path: Path

    def __init__(self, path: Path) -> None:
        """Create the error for an existing output file.

        Args:
            path: The output file.
        """
        super().__init__(
            f"output file '{path}' already exists", hint="pass force=True to replace it"
        )
        self.path = path


def write_output_file(path: Path, text: str, *, force: bool) -> None:
    """Write an output file with mode `0600`.

    Without `force` the file is created exclusively (`O_CREAT | O_EXCL`, so no existing file
    or symlink is touched); with `force` a temporary file in the same directory replaces it
    atomically.

    Args:
        path: The output file.
        text: The content, written as UTF-8 without newline translation.
        force: Replace an existing file.

    Raises:
        OutputFileExistsError: The file exists and `force` is not set.
        ValidationError: The path holds a NUL character.
        BackendError: Any other OS error; no partial or temporary file is left behind.
    """
    _check_path(path, what="output file")
    data = text.encode("utf-8")
    if force:
        _replace(path, data)
    else:
        _create(path, data)


def _check_path(path: Path, *, what: str) -> None:
    if "\0" in str(path):
        # The OS refuses such a path with a ValueError, not an OSError.
        message = f"{what} path {str(path)!r} contains a NUL character"
        raise ValidationError(message)


def _create(path: Path, data: bytes) -> None:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _MODE)
    except FileExistsError as err:
        raise OutputFileExistsError(path) from err
    except OSError as err:
        raise _write_error(path, err) from err
    _write(fd, data, path=path, partial=path)


def _replace(path: Path, data: bytes) -> None:
    try:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as err:
        raise _write_error(path, err) from err
    temporary = Path(name)
    _write(fd, data, path=path, partial=temporary)
    try:
        temporary.replace(path)
    except OSError as err:
        temporary.unlink(missing_ok=True)
        raise _write_error(path, err) from err


def _write(fd: int, data: bytes, *, path: Path, partial: Path) -> None:
    try:
        # The umask may have removed bits only; make the mode exact.
        os.fchmod(fd, _MODE)
        with os.fdopen(fd, "wb", closefd=False) as file:
            file.write(data)
            file.flush()
            os.fsync(fd)
    except OSError as err:
        os.close(fd)
        partial.unlink(missing_ok=True)
        raise _write_error(path, err) from err
    os.close(fd)


def _write_error(path: Path, err: OSError) -> BackendError:
    return BackendError(f"cannot write '{path}': {err.strerror}")


def read_input_file(path: Path) -> str:
    """Read an input file as strict UTF-8, without newline translation.

    Args:
        path: The input file.

    Returns:
        The text exactly as stored.

    Raises:
        BackendError: The file cannot be read.
        ValidationError: The file is not UTF-8, or the path holds a NUL character.
    """
    _check_path(path, what="input file")
    try:
        data = path.read_bytes()
    except OSError as err:
        message = f"cannot read '{path}': {err.strerror}"
        raise BackendError(message) from err
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        message = f"'{path}' is not valid UTF-8"
        # Not chained: the decode error holds raw content, which may be secret.
        raise ValidationError(message) from None
