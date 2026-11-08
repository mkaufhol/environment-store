"""`ExportFlow`: the steps of an export from the stores screen.

Stores in order, options, output path (each a dialog, `screens.export`), then the keys of the
encrypted stores in load order: `ENV_STORE_KEY_<STORE>`, the project file's `[keys]`, else
the unlock dialog. The file is written through the library, mode `0600`, in output order.
Cancelling any step ends the export without writing anything.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from textual.app import App

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.library.sources import Source
from environment_store.tui.choices import ExportOptions, ExportTarget
from environment_store.tui.messages import notify_done, notify_error, notify_problem
from environment_store.tui.screens.export import (
    ExportOptionsScreen,
    ExportPathScreen,
    ExportStoresScreen,
)
from environment_store.tui.screens.unlock import UnlockScreen
from environment_store.tui.session import OpenedStore, StoreSession
from environment_store.tui.unlocking import open_without_asking

__all__ = ["ExportFlow"]


class ExportFlow:
    """One export, driven by the dialogs' results."""

    _app: App[object]
    _session: StoreSession
    _stores: Mapping[str, StoreInfo]
    _chosen: tuple[str, ...]

    def __init__(
        self, app: App[object], session: StoreSession, stores: Sequence[StoreInfo]
    ) -> None:
        """Prepare an export.

        Args:
            app: The running app.
            session: The TUI's store session.
            stores: The listed stores to choose from.
        """
        self._app = app
        self._session = session
        self._stores = MappingProxyType({info.name: info for info in stores})
        self._chosen = ()

    def start(self) -> None:
        """Ask for the stores (step 1)."""
        if not self._stores:
            notify_problem(self._app, "there are no stores to export")
            return
        self._app.push_screen(ExportStoresScreen(list(self._stores.values())), self._stores_chosen)

    def _stores_chosen(self, chosen: list[str] | None) -> None:
        if chosen is None:
            return
        self._chosen = tuple(chosen)
        dialog = ExportOptionsScreen(chosen, first_wins=not self._session.ordered_overwrite)
        self._app.push_screen(dialog, self._options_chosen)

    def _options_chosen(self, options: ExportOptions | None) -> None:
        if options is not None:
            self._app.push_screen(ExportPathScreen(options), self._target_chosen)

    def _target_chosen(self, target: ExportTarget | None) -> None:
        if target is not None:
            self._resolve(target, [])

    def _resolve(self, target: ExportTarget, sources: list[Source]) -> None:
        """Add the next stores' sources; ask for a key where none is found, then write."""
        while len(sources) < len(self._chosen):
            info = self._stores[self._chosen[len(sources)]]
            if not info.encrypted:
                sources.append(Source(info.name))
                continue
            opened = open_without_asking(self._app, self._session, info)
            if opened is None:
                self._ask(target, info, sources)
                return
            sources.append(_source(opened))
        self._write(target, sources)

    def _ask(self, target: ExportTarget, info: StoreInfo, sources: list[Source]) -> None:
        def unlocked(opened: OpenedStore | None) -> None:
            if opened is not None:
                self._resolve(target, [*sources, _source(opened)])

        self._app.push_screen(UnlockScreen(self._session, info), unlocked)

    def _write(self, target: ExportTarget, sources: list[Source]) -> None:
        try:
            self._session.export(sources, target.path, target.options, force=target.replace)
        except EnvironmentStoreError as error:
            notify_error(self._app, error)
            return
        notify_done(self._app, f"exported to '{target.path}'")


def _source(opened: OpenedStore) -> Source:
    # A key from ENV_STORE_KEY_<STORE> is left to the library, which then also refuses stores
    # that share one key variable.
    return Source(opened.name, key=None if opened.from_environment else opened.secret)
