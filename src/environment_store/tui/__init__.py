"""The terminal user interface (spec §6.14, D15, D31, PD 29).

Needs the `tui` extra (textual); without it, importing this package raises
`MissingExtraError` with the install hint. Imports `core`, `config`, `library` and `formats`
only; it never imports the CLI (PD 31). `run_tui` and `EnvironmentStoreApp` are resolved on
first use, like the package's public API (PD 1), so importing this package loads no library
code.
"""

import importlib
from typing import TYPE_CHECKING, Final

from environment_store.core.errors import MissingExtraError

try:
    import textual  # noqa: F401 - probes the optional extra before anything else needs it
except ImportError as missing:
    extra = "tui"
    raise MissingExtraError(extra) from missing

if TYPE_CHECKING:
    from environment_store.tui.app import EnvironmentStoreApp, run_tui

__all__ = ["EnvironmentStoreApp", "run_tui"]

_APP_MODULE: Final = "environment_store.tui.app"


def __getattr__(name: str) -> object:
    """Resolve `run_tui` and `EnvironmentStoreApp` on first use.

    Args:
        name: The attribute.

    Returns:
        The public object.

    Raises:
        AttributeError: The name is not part of this package's API.
    """
    if name not in __all__:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)
    return getattr(importlib.import_module(_APP_MODULE), name)
