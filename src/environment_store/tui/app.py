"""`EnvironmentStoreApp` and `run_tui`: the Textual app on the library facade (D31, PD 29).

Browse stores, unlock encrypted ones (project `[keys]` first), view masked values and add,
edit or delete variables. Store lifecycle, import / export and key lifecycle stay in the CLI.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.screen import Screen

from environment_store.config.secrets import read_secret_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.screens.stores import StoresScreen
from environment_store.tui.session import ReadKeyFile, StoreSession

__all__ = ["EnvironmentStoreApp", "run_tui"]


class EnvironmentStoreApp(App[None]):
    """The TUI over one open `EnvironmentStore`."""

    TITLE: str | None = "Environment Store"
    CSS: ClassVar[str] = """
    ModalScreen {
        align: center middle;
    }
    .dialog {
        width: 80;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }
    .dialog TextArea {
        height: 10;
    }
    .buttons {
        height: auto;
        margin-top: 1;
    }
    .buttons Button {
        margin-right: 2;
    }
    """

    _session: StoreSession

    def __init__(
        self,
        store: EnvironmentStore,
        *,
        key_paths: Mapping[str, Path],
        read_key_file: ReadKeyFile = read_secret_file,
    ) -> None:
        """Create the app.

        Args:
            store: The open store; the caller closes it after the app ends.
            key_paths: The project file's `[keys]`, tried before asking (PD 5).
            read_key_file: Reads key and passphrase files.
        """
        super().__init__()
        self._session = StoreSession(store, key_paths=key_paths, read_key_file=read_key_file)

    def get_default_screen(self) -> Screen[None]:
        """Start with the list of stores."""
        return StoresScreen(self._session)


def run_tui(store: EnvironmentStore, *, key_paths: Mapping[str, Path]) -> None:
    """Run the TUI in the terminal until the user quits.

    Args:
        store: The open store; the caller closes it.
        key_paths: The project file's `[keys]`.
    """
    EnvironmentStoreApp(store, key_paths=key_paths).run()
