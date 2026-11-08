"""The Unlock dialog says what each field takes for the store's key mode.

The hidden field takes the key text of a `keyfile` store or the passphrase of a `passphrase`
store; the path field takes a file only. Key text typed into the visible path field is refused
and cleared instead of being read as a path.
"""

from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import Input

from environment_store.core.models import KeyMode
from environment_store.core.secrets import Passphrase
from environment_store.library.keys import generate_key_file
from environment_store.library.store import EnvironmentStore
from environment_store.tui.app import EnvironmentStoreApp
from environment_store.tui.screens.unlock import UnlockScreen, unlock_wording
from environment_store.tui.screens.variables import MASK, VariablesScreen
from tests.tui.pilot import notifications, rows, run_app, set_input


@pytest.fixture
def key(tmp_path: Path) -> Path:
    path = tmp_path / "a.key"
    generate_key_file(path)
    return path


@pytest.fixture
def encrypted(store: EnvironmentStore, key: Path) -> EnvironmentStore:
    """Store `a` encrypted with `key`, holding SECRET=hidden-value."""
    store.create_store("a", encrypt=True, key=key)
    store.set("a", "SECRET", "hidden-value", key=key)
    return store


@pytest.fixture
def passphrase_store(store: EnvironmentStore) -> EnvironmentStore:
    """Store `p` with the passphrase `correct horse`."""
    secret = Passphrase(text="correct horse")
    store.create_store("p", encrypt=True, key=secret)
    store.set("p", "SECRET", "hidden-value", key=secret)
    return store


async def _open_first(pilot: Pilot[None]) -> None:
    await pilot.press("enter")
    await pilot.pause()


def _placeholders(app: EnvironmentStoreApp) -> tuple[str, str]:
    return (
        str(app.screen.query_one("#path", Input).placeholder),
        str(app.screen.query_one("#passphrase", Input).placeholder),
    )


@pytest.mark.parametrize(
    ("mode", "path", "secret"),
    [
        (KeyMode.KEYFILE, "Key file path, e.g. ~/.keys/a.key", "or paste the key itself"),
        (KeyMode.PASSPHRASE, "Passphrase file path, e.g. ~/.keys/a.pass", "or type the passphrase"),
        (None, "Key or passphrase file path", "or paste the key or type the passphrase"),
    ],
)
def test_the_placeholders_name_what_each_field_takes(
    mode: KeyMode | None, path: str, secret: str
) -> None:
    wording = unlock_wording(mode)
    assert (wording.path_placeholder, wording.hidden_placeholder) == (path, secret)


def test_a_keyfile_store_asks_for_the_key_file_path_or_the_key(encrypted: EnvironmentStore) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert _placeholders(app) == (
            "Key file path, e.g. ~/.keys/a.key",
            "or paste the key itself",
        )

    run_app(encrypted, scenario)


def test_a_passphrase_store_asks_for_a_passphrase_file_or_the_passphrase(
    passphrase_store: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        assert _placeholders(app) == (
            "Passphrase file path, e.g. ~/.keys/a.pass",
            "or type the passphrase",
        )

    run_app(passphrase_store, scenario)


def test_the_pasted_key_unlocks_a_keyfile_store(encrypted: EnvironmentStore, key: Path) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#passphrase", key.read_text(encoding="utf-8").strip())
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, VariablesScreen)
        assert rows(app) == [["SECRET", MASK]]

    run_app(encrypted, scenario)


def test_a_wrong_pasted_key_is_named_as_the_pasted_key(
    encrypted: EnvironmentStore, tmp_path: Path
) -> None:
    other = tmp_path / "other.key"
    generate_key_file(other)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#passphrase", other.read_text(encoding="utf-8").strip())
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == [
            "unlocking with the pasted key failed: cannot decrypt store 'a': wrong key or "
            "passphrase, or the stored data was modified"
        ]

    run_app(encrypted, scenario)


def test_text_that_is_not_a_key_in_the_hidden_field_of_a_keyfile_store_is_refused(
    encrypted: EnvironmentStore,
) -> None:
    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#passphrase", "correct horse")
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        assert notifications(app) == [
            "unlocking with the pasted key failed: not a valid key file: expected one line "
            "'envstore-key-v1:<base64url of 32 bytes>'; create one with envs keygen"
        ]

    run_app(encrypted, scenario)


@pytest.mark.parametrize("fixture", ["encrypted", "passphrase_store"])
def test_key_text_in_the_path_field_is_refused_and_cleared(
    request: pytest.FixtureRequest, key: Path, fixture: str
) -> None:
    # The path field shows what is typed: a key there is on screen, so it is wiped, not used.
    store: EnvironmentStore = request.getfixturevalue(fixture)
    text = key.read_text(encoding="utf-8").strip()

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await set_input(pilot, "#path", text)
        await pilot.click("#unlock")
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        [message] = notifications(app)
        assert message == ("that is a key, not a file path: paste it into the hidden field below")
        assert text not in message
        assert app.screen.query_one("#path", Input).value == ""

    run_app(store, scenario)


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("encrypted", "enter either the key file path or the key itself"),
        ("passphrase_store", "enter either a passphrase file path or the passphrase"),
    ],
)
def test_unlock_needs_exactly_one_field_in_the_stores_words(
    request: pytest.FixtureRequest, fixture: str, message: str
) -> None:
    store: EnvironmentStore = request.getfixturevalue(fixture)

    async def scenario(pilot: Pilot[None], app: EnvironmentStoreApp) -> None:
        await _open_first(pilot)
        await pilot.click("#unlock")
        await pilot.pause()
        assert notifications(app) == [message]

    run_app(store, scenario)


def test_the_unknown_mode_wording_covers_both_kinds() -> None:
    wording = unlock_wording(None)
    assert wording.typed_source == "the typed key or passphrase"
    assert wording.missing == (
        "enter either a key or passphrase file path, or the key or passphrase itself"
    )
