"""`ENV_STORE_KEY_<STORE>` in the library: `EnvironmentStore` methods, `load` (§4.3, D53)."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import pytest

from environment_store.config.project import PROJECT_FILE_NAME
from environment_store.config.settings import resolve_settings
from environment_store.core.errors import (
    DecryptionError,
    InvalidKeyFileError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.crypto.keyfile import format_key
from environment_store.library.environment import Environment
from environment_store.library.oneliner import load_with
from environment_store.library.sources import KeyInput, Source
from environment_store.library.store import EnvironmentStore
from tests.support.clock import FakeClock
from tests.support.kdf import CheapKdf
from tests.unit.library.conftest import CONNECTION, KEY, OTHER_KEY, PASSPHRASE, RecordingOpener

CANARY: Final = "do-not-echo-this-value"
KEY_TEXT: Final = format_key(KEY)

type MakeStore = Callable[[Mapping[str, str] | None], EnvironmentStore]


@pytest.fixture
def make(opener: RecordingOpener, clock: FakeClock, kdf: CheapKdf) -> MakeStore:
    def make(environ: Mapping[str, str] | None) -> EnvironmentStore:
        return EnvironmentStore(
            CONNECTION, clock=clock, kdf_params_factory=kdf, opener=opener, environ=environ
        )

    return make


@pytest.fixture
def seeded(make: MakeStore) -> None:
    with make({}) as store:
        store.create_store("base")
        store.set("base", "HOST", "base")
        store.create_store("keyed", encrypt=True, key=KEY)
        store.set("keyed", "API_URL", "k", key=KEY)
        store.create_store("phrased", encrypt=True, key=PASSPHRASE)
        store.set("phrased", "WORD", "w", key=PASSPHRASE)


# --- EnvironmentStore methods ---------------------------------------------------------------------


@pytest.mark.usefixtures("seeded")
def test_variables_and_get_take_the_key_from_the_variable(make: MakeStore) -> None:
    with make(
        {"ENV_STORE_KEY_KEYED": KEY_TEXT, "ENV_STORE_KEY_PHRASED": "correct horse battery staple\n"}
    ) as store:
        assert store.variables("keyed") == {"API_URL": "k"}
        assert store.get("phrased", "WORD") == "w"


@pytest.mark.usefixtures("seeded")
def test_writes_take_the_key_from_the_variable(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_KEYED": KEY_TEXT}) as store:
        store.set("keyed", "NEW", "1")
        store.set_many("keyed", {"MORE": "2"})
        store.delete("keyed", ["API_URL"])

    with make({}) as store:
        assert store.variables("keyed", key=KEY) == {"MORE": "2", "NEW": "1"}


@pytest.mark.usefixtures("seeded")
def test_an_explicit_key_beats_the_variable(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_KEYED": ""}) as store:
        assert store.variables("keyed", key=KEY) == {"API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_a_wrong_key_in_the_variable_is_a_decryption_error(make: MakeStore) -> None:
    with (
        make({"ENV_STORE_KEY_KEYED": format_key(OTHER_KEY)}) as store,
        pytest.raises(DecryptionError),
    ):
        store.variables("keyed")


@pytest.mark.usefixtures("seeded")
def test_an_empty_variable_is_a_key_source_error_naming_it(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_KEYED": ""}) as store, pytest.raises(KeySourceError) as caught:
        store.variables("keyed")

    assert "ENV_STORE_KEY_KEYED" in str(caught.value)


@pytest.mark.usefixtures("seeded")
def test_invalid_key_text_never_shows_the_value(make: MakeStore) -> None:
    with (
        make({"ENV_STORE_KEY_KEYED": CANARY}) as store,
        pytest.raises(InvalidKeyFileError) as caught,
    ):
        store.variables("keyed")

    assert "ENV_STORE_KEY_KEYED" in str(caught.value)
    assert CANARY not in str(caught.value)


@pytest.mark.usefixtures("seeded")
def test_the_variable_of_a_plaintext_store_is_ignored(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_BASE": CANARY}) as store:
        assert store.variables("base") == {"HOST": "base"}
        store.set("base", "X", "1")


@pytest.mark.usefixtures("seeded")
def test_without_a_variable_the_missing_key_hint_names_it(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(KeyRequiredError) as caught:
        store.variables("keyed")

    assert str(caught.value) == str(KeyRequiredError.for_store("keyed"))
    assert "ENV_STORE_KEY_KEYED" in str(caught.value)


@pytest.mark.usefixtures("seeded")
def test_environment_secret_returns_the_secret_or_none(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_KEYED": KEY_TEXT, "ENV_STORE_KEY_BASE": "x"}) as store:
        assert store.environment_secret("keyed") == KEY
        assert store.environment_secret("phrased") is None
        assert store.environment_secret("base") is None


@pytest.mark.usefixtures("seeded")
def test_rekey_takes_the_old_key_from_the_variable_but_never_the_new_one(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_KEYED": KEY_TEXT}) as store:
        store.rekey_store("keyed", new=OTHER_KEY)

    with make({}) as store:
        assert store.variables("keyed", key=OTHER_KEY) == {"API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_rekey_without_an_old_key_anywhere_needs_one(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(KeyRequiredError):
        store.rekey_store("keyed", new=OTHER_KEY)


@pytest.mark.usefixtures("seeded")
def test_rekey_of_a_plaintext_store_is_refused(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_BASE": KEY_TEXT}) as store, pytest.raises(NotEncryptedError):
        store.rekey_store("base", new=OTHER_KEY)


@pytest.mark.usefixtures("seeded")
def test_copy_and_move_take_the_source_key_from_the_variable(make: MakeStore) -> None:
    environ = {"ENV_STORE_KEY_KEYED": KEY_TEXT, "ENV_STORE_KEY_COPY": format_key(OTHER_KEY)}
    with make(environ) as store:
        store.copy_store("keyed", "copy")
        store.move_store("keyed", "moved")

    with make({}) as store:
        # "same" keeps the source's key; the copy's variable is never a new key.
        assert store.variables("copy", key=KEY) == {"API_URL": "k"}
        assert store.variables("moved", key=KEY) == {"API_URL": "k"}


def test_new_keys_never_come_from_the_variable(make: MakeStore) -> None:
    with make({"ENV_STORE_KEY_FRESH": KEY_TEXT, "ENV_STORE_KEY_LATER": KEY_TEXT}) as store:
        with pytest.raises(ValidationError):
            store.create_store("fresh", encrypt=True)
        store.create_store("later")
        assert not store.store_info("later").encrypted


@pytest.mark.usefixtures("seeded")
def test_the_default_environment_is_os_environ(
    make: MakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENV_STORE_KEY_KEYED", KEY_TEXT)

    with make(None) as store:
        assert store.variables("keyed") == {"API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_from_env_and_from_settings_pass_the_environment_on(
    opener: RecordingOpener, kdf: CheapKdf, tmp_path: Path
) -> None:
    environ = {"ENV_STORE_CONNECTION": CONNECTION, "ENV_STORE_KEY_KEYED": KEY_TEXT}
    with EnvironmentStore.from_env(environ=environ, opener=opener, kdf_params_factory=kdf) as store:
        assert store.variables("keyed") == {"API_URL": "k"}
    settings = resolve_settings(
        connection=None, use_project=False, environ=environ, cwd=tmp_path, boundary=tmp_path
    )
    with EnvironmentStore.from_settings(settings, opener=opener, environ=environ) as store:
        assert store.variables("keyed") == {"API_URL": "k"}


# --- EnvironmentStore.load ------------------------------------------------------------------------


@pytest.mark.usefixtures("seeded")
def test_load_takes_keys_from_variables(make: MakeStore) -> None:
    environ = {"ENV_STORE_KEY_KEYED": KEY_TEXT, "ENV_STORE_KEY_PHRASED": PASSPHRASE.text}
    with make(environ) as store:
        environment = store.load(["base", Source("keyed"), "phrased"])

    assert environment.variables() == {"API_URL": "k", "HOST": "base", "WORD": "w"}


@pytest.mark.usefixtures("seeded")
def test_load_with_colliding_stores_and_a_set_variable_is_refused(make: MakeStore) -> None:
    with make({}) as store:
        store.create_store("my-app", encrypt=True, key=KEY)
        store.create_store("my_app", encrypt=True, key=OTHER_KEY)

    with (
        make({"ENV_STORE_KEY_MY_APP": KEY_TEXT}) as store,
        pytest.raises(ValidationError) as caught,
    ):
        store.load(["my-app", "my_app"])

    assert "ENV_STORE_KEY_MY_APP" in str(caught.value)


@pytest.mark.usefixtures("seeded")
def test_load_with_keys_for_both_colliding_stores_is_fine(make: MakeStore) -> None:
    with make({}) as store:
        store.create_store("my-app", encrypt=True, key=KEY)
        store.create_store("my_app", encrypt=True, key=OTHER_KEY)

    with make({"ENV_STORE_KEY_MY_APP": ""}) as store:
        environment = store.load([Source("my-app", key=KEY), Source("my_app", key=OTHER_KEY)])

    assert environment.variables() == {}


# --- the one-liner --------------------------------------------------------------------------------


def _load(
    tmp_path: Path,
    opener: RecordingOpener,
    *stores: str,
    environ: Mapping[str, str],
    keys: Mapping[str, KeyInput] | None = None,
) -> Environment:
    return load_with(
        stores,
        connection=CONNECTION,
        keys=keys,
        first_wins=False,
        overwrite=False,
        nested=False,
        use_project=True,
        noinput=True,
        environ=environ,
        cwd=tmp_path,
        boundary=tmp_path,
        interactive=False,
        prompter=_NoPrompter(),
        target={},
        opener=opener,
    )


class _NoPrompter:
    def secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def new_secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def confirm(self, question: str) -> bool:
        raise AssertionError(question)


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_takes_keys_from_variables(tmp_path: Path, opener: RecordingOpener) -> None:
    environ = {"ENV_STORE_KEY_KEYED": KEY_TEXT, "ENV_STORE_KEY_PHRASED": PASSPHRASE.text}

    environment = _load(tmp_path, opener, "base", "keyed", "phrased", environ=environ)

    assert environment.variables() == {"API_URL": "k", "HOST": "base", "WORD": "w"}


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_prefers_the_variable_to_the_project_key(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    wrong = tmp_path / "wrong.key"
    wrong.write_text(format_key(OTHER_KEY), encoding="ascii")
    (tmp_path / PROJECT_FILE_NAME).write_text(f"[keys]\nkeyed = '{wrong}'\n", encoding="utf-8")

    environment = _load(tmp_path, opener, "keyed", environ={"ENV_STORE_KEY_KEYED": KEY_TEXT})

    assert environment.variables() == {"API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_prefers_keys_to_the_variable(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    environment = _load(
        tmp_path, opener, "keyed", environ={"ENV_STORE_KEY_KEYED": ""}, keys={"keyed": KEY}
    )

    assert environment.variables() == {"API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_refuses_colliding_stores(
    tmp_path: Path, opener: RecordingOpener, make: MakeStore
) -> None:
    with make({}) as store:
        store.create_store("my-app")
        store.create_store("my_app")

    with pytest.raises(ValidationError, match="ENV_STORE_KEY_MY_APP"):
        _load(tmp_path, opener, "my-app", "my_app", environ={"ENV_STORE_KEY_MY_APP": "x"})


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_missing_key_names_the_variable(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    with pytest.raises(KeyRequiredError, match="ENV_STORE_KEY_PHRASED"):
        _load(tmp_path, opener, "phrased", environ={})


@pytest.mark.usefixtures("seeded")
def test_the_one_liner_does_not_change_the_variables(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    environ = {"ENV_STORE_KEY_KEYED": KEY_TEXT}

    _load(tmp_path, opener, "keyed", environ=environ)

    assert environ == {"ENV_STORE_KEY_KEYED": KEY_TEXT}
    assert "ENV_STORE_KEY_KEYED" not in os.environ
