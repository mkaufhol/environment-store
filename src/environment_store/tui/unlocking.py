"""Open a store without asking, with the keys the TUI finds itself (D53, PD 5).

An encrypted store is opened with the key from `ENV_STORE_KEY_<STORE>` (D53), else with the
project file's key when it names one (PD 5). When neither gives a working key, the caller asks
with the `UnlockScreen`; a key that does not fit is reported, naming where it came from.
"""

import dataclasses

from textual.app import App

from environment_store.core.errors import EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.core.names import key_variable
from environment_store.tui.messages import message_for, notify_problem
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["open_without_asking"]


def open_without_asking(
    app: App[object], session: StoreSession, info: StoreInfo
) -> OpenedStore | None:
    """Open a store directly, or with its key variable or project key.

    Args:
        app: The running app, for notifications about keys that do not fit.
        session: The TUI's store session.
        info: The store's listing entry.

    Returns:
        The opened store, or `None` when the user has to be asked for the key.

    Raises:
        EnvironmentStoreError: A plaintext store cannot be opened.
    """
    name = info.name
    if not info.encrypted:
        return session.open(name)
    # D53: the key variable comes before the project key; when set, it alone is tried.
    try:
        secret = session.environment_secret(name)
        if secret is not None:
            return dataclasses.replace(session.open(name, secret), from_environment=True)
    except EnvironmentStoreError as error:
        _notify_failed(app, key_variable(name), error)
        return None
    return _open_with_project_key(app, session, name)


def _open_with_project_key(
    app: App[object], session: StoreSession, name: str
) -> OpenedStore | None:
    path = session.project_key(name)
    if path is None:
        return None
    try:
        return session.open(name, session.secret_from_file(name, path))
    except EnvironmentStoreError as error:
        _notify_failed(app, f"the key file '{path}' from the project file", error)
        return None


def _notify_failed(app: App[object], source: str, error: EnvironmentStoreError) -> None:
    # The user did not choose this key, so the message names it and where it came from.
    notify_problem(app, f"unlocking with {source} failed: {message_for(error)}")
