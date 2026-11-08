"""Open a store without asking, with the keys the TUI finds itself.

An encrypted store is opened with the key from the environment (`ENV_STORE_KEY_<STORE>` or
`ENV_STORE_LOAD`), else with the project file's key when it names one. When neither gives a working
key, the caller asks with the `UnlockScreen`; a key that does not fit is reported, naming where it
came from.
"""

import dataclasses

from textual.app import App

from environment_store.config.load_spec import ENV_LOAD
from environment_store.core.errors import ConfigurationError, EnvironmentStoreError
from environment_store.core.models import StoreInfo
from environment_store.core.names import key_variable
from environment_store.tui.messages import message_for, notify_problem
from environment_store.tui.session import OpenedStore, StoreSession

__all__ = ["open_without_asking"]


def open_without_asking(
    app: App[object], session: StoreSession, info: StoreInfo
) -> OpenedStore | None:
    """Open a store directly, or with its key from the environment or its project key.

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
    # The environment comes before the project key; when it has a key, that alone is tried.
    try:
        secret = session.environment_secret(name)
        if secret is not None:
            return dataclasses.replace(session.open(name, secret), from_environment=True)
    except EnvironmentStoreError as error:
        _notify_failed(app, _environment_source(session, name), error)
        return None
    return _open_with_project_key(app, session, name)


def _environment_source(session: StoreSession, name: str) -> str:
    try:
        return session.environment_key_source(name) or key_variable(name)
    except ConfigurationError:
        # An invalid ENV_STORE_LOAD is the error being reported; naming it must not raise again.
        return ENV_LOAD


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
