"""What the TUI's dialogs hand to the session: a new store's key, the export options.

The new-key choices are the encryption options of `create-store` (spec §6.3, D55); the export
options are those of `export` (spec §6.11, D56).
"""

from dataclasses import dataclass, field
from pathlib import Path

from environment_store.core.secrets import Passphrase
from environment_store.formats.infer import Format

__all__ = [
    "ExportOptions",
    "ExportTarget",
    "GenerateKey",
    "KeyFile",
    "NewKey",
    "TypedPassphrase",
]


@dataclass(frozen=True, slots=True)
class GenerateKey:
    """Generate a new key file (`--generate-key`): mode `0600`, never overwritten.

    Attributes:
        path: Where to create it.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class KeyFile:
    """Use an existing key file (`-k`).

    Attributes:
        path: The key file.
    """

    path: Path


@dataclass(frozen=True, slots=True)
class TypedPassphrase:
    """Use a passphrase typed twice (`--passphrase`).

    Attributes:
        passphrase: The passphrase.
    """

    passphrase: Passphrase = field(repr=False)


type NewKey = GenerateKey | KeyFile | TypedPassphrase
"""The secret of a new encrypted store."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportOptions:
    """The options of an export (`-t`, `--nested`, `--first-wins`).

    Attributes:
        fmt: The file format.
        nested: One namespace per store instead of merging.
        first_wins: The first store wins instead of the last.
    """

    fmt: Format
    nested: bool
    first_wins: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportTarget:
    """Where and how an export is written.

    Attributes:
        path: The output file.
        options: Format, nested and merge order.
        replace: Replace an existing file (`--force`); confirmed by the user.
    """

    path: Path
    options: ExportOptions
    replace: bool
