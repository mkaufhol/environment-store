"""`ENV_STORE_LOAD` in the library: building a load specification, and loading from one.

`EnvironmentStore.load_spec` resolves every key like `load`, decrypts each store to prove it,
and returns the specification. `load()` without store names loads the stores of
`ENV_STORE_LOAD`, with its keys.
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import pytest

from environment_store import LoadSpec as PublicLoadSpec
from environment_store import load
from environment_store.config.load_spec import LoadSpec
from environment_store.core.errors import (
    ConfigurationError,
    DecryptionError,
    KeyRequiredError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.secrets import Passphrase
from environment_store.crypto.keyfile import format_key
from environment_store.library.environment import Environment
from environment_store.library.oneliner import load_with
from environment_store.library.sources import KeyInput, Source
from environment_store.library.store import EnvironmentStore
from tests.support.clock import FakeClock
from tests.support.kdf import CheapKdf
from tests.unit.library.conftest import CONNECTION, KEY, OTHER_KEY, PASSPHRASE, RecordingOpener

CANARY: Final = "do-not-echo-this-value"

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


def _spec() -> LoadSpec:
    return LoadSpec(stores=("base", "keyed", "phrased"), keys={"keyed": KEY, "phrased": PASSPHRASE})


# --- building -------------------------------------------------------------------------------------


def test_the_public_name_is_the_config_class() -> None:
    assert PublicLoadSpec is LoadSpec


@pytest.mark.usefixtures("seeded")
def test_load_spec_holds_the_stores_in_order_and_the_keys_of_encrypted_ones(
    make: MakeStore,
) -> None:
    with make({}) as store:
        spec = store.load_spec(
            ["base", Source("keyed", key=KEY), Source("phrased", key=PASSPHRASE), "base"]
        )

    assert spec.stores == ("base", "keyed", "phrased", "base")
    assert dict(spec.keys) == {"keyed": KEY, "phrased": PASSPHRASE}
    assert LoadSpec.decode(spec.encode()) == spec


@pytest.mark.usefixtures("seeded")
def test_load_spec_reads_key_files_by_the_store_key_mode(make: MakeStore, tmp_path: Path) -> None:
    phrase_file = tmp_path / "phrase.txt"
    phrase_file.write_text(PASSPHRASE.text + "\n", encoding="utf-8")

    with make({}) as store:
        spec = store.load_spec([Source("phrased", key=phrase_file)])

    assert spec.keys["phrased"] == PASSPHRASE


@pytest.mark.usefixtures("seeded")
def test_load_spec_takes_keys_from_the_environment(make: MakeStore) -> None:
    environ = {
        "ENV_STORE_KEY_KEYED": format_key(KEY),
        "ENV_STORE_LOAD": LoadSpec(stores=("phrased",), keys={"phrased": PASSPHRASE}).encode(),
    }

    with make(environ) as store:
        spec = store.load_spec(["keyed", "phrased"])

    assert dict(spec.keys) == {"keyed": KEY, "phrased": PASSPHRASE}


@pytest.mark.usefixtures("seeded")
def test_load_spec_proves_every_key_by_decrypting(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(DecryptionError):
        store.load_spec([Source("keyed", key=OTHER_KEY)])


@pytest.mark.usefixtures("seeded")
def test_load_spec_needs_the_key_of_every_encrypted_store(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(KeyRequiredError):
        store.load_spec(["base", "keyed"])


@pytest.mark.usefixtures("seeded")
def test_load_spec_refuses_a_key_for_a_plaintext_store(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(NotEncryptedError):
        store.load_spec([Source("base", key=KEY)])


@pytest.mark.usefixtures("seeded")
def test_load_spec_refuses_a_single_string(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(ValidationError, match="not a single string"):
        store.load_spec("base")


@pytest.mark.usefixtures("seeded")
def test_load_spec_refuses_an_empty_list(make: MakeStore) -> None:
    with make({}) as store, pytest.raises(ValidationError, match="at least one store"):
        store.load_spec([])


# --- EnvironmentStore methods with keys from the spec -------------------------------------------


@pytest.mark.usefixtures("seeded")
def test_store_methods_take_keys_from_the_spec(make: MakeStore) -> None:
    with make({"ENV_STORE_LOAD": _spec().encode()}) as store:
        assert store.variables("keyed") == {"API_URL": "k"}
        assert store.get("phrased", "WORD") == "w"
        assert store.environment_secret("phrased") == PASSPHRASE
        assert store.load(["base", "keyed"]).variables() == {"HOST": "base", "API_URL": "k"}


@pytest.mark.usefixtures("seeded")
def test_store_methods_refuse_a_key_in_both_variables(make: MakeStore) -> None:
    environ = {"ENV_STORE_KEY_KEYED": CANARY, "ENV_STORE_LOAD": _spec().encode()}

    with make(environ) as store, pytest.raises(ValidationError, match="from both") as caught:
        store.variables("keyed")

    assert CANARY not in str(caught.value)


@pytest.mark.usefixtures("seeded")
def test_an_explicit_key_beats_the_spec(make: MakeStore) -> None:
    spec = LoadSpec(stores=("keyed",), keys={"keyed": OTHER_KEY})

    with make({"ENV_STORE_LOAD": spec.encode()}) as store:
        assert store.variables("keyed", key=KEY) == {"API_URL": "k"}


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
def test_the_one_liner_loads_the_stores_and_keys_of_the_spec(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    environment = _load(tmp_path, opener, environ={"ENV_STORE_LOAD": _spec().encode()})

    assert [name for name, _ in environment.stores] == ["base", "keyed", "phrased"]
    assert environment.variables() == {"HOST": "base", "API_URL": "k", "WORD": "w"}


@pytest.mark.usefixtures("seeded")
def test_named_stores_replace_the_spec_stores_but_keep_its_keys(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    environment = _load(tmp_path, opener, "phrased", environ={"ENV_STORE_LOAD": _spec().encode()})

    assert environment.variables() == {"WORD": "w"}


@pytest.mark.usefixtures("seeded")
def test_the_spec_stores_win_over_the_project_file(tmp_path: Path, opener: RecordingOpener) -> None:
    (tmp_path / ".envstore.toml").write_text('stores = ["keyed"]\n', encoding="utf-8")
    spec = LoadSpec(stores=("base",))

    environment = _load(tmp_path, opener, environ={"ENV_STORE_LOAD": spec.encode()})

    assert environment.variables() == {"HOST": "base"}


@pytest.mark.usefixtures("seeded")
def test_explicit_keys_beat_the_spec(tmp_path: Path, opener: RecordingOpener) -> None:
    spec = LoadSpec(stores=("phrased",), keys={"phrased": Passphrase(text="wrong")})

    environment = _load(
        tmp_path, opener, environ={"ENV_STORE_LOAD": spec.encode()}, keys={"phrased": PASSPHRASE}
    )

    assert environment.variables() == {"WORD": "w"}


def test_without_names_spec_or_project_the_message_names_all_three(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    with pytest.raises(ConfigurationError, match=r"name them.*set ENV_STORE_LOAD.*\.envstore"):
        _load(tmp_path, opener, environ={})


def test_a_malformed_spec_stops_the_one_liner(tmp_path: Path, opener: RecordingOpener) -> None:
    with pytest.raises(ConfigurationError, match="ENV_STORE_LOAD") as caught:
        _load(tmp_path, opener, "base", environ={"ENV_STORE_LOAD": CANARY})

    assert CANARY not in str(caught.value)


def test_the_public_one_liner_needs_only_two_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = f"json://{tmp_path}/stores"
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf(), environ={}) as store:
        store.create_store("base")
        store.set("base", "HOST", "base")
        store.create_store("phrased", encrypt=True, key=PASSPHRASE)
        store.set("phrased", "SPEC_WORD", "w", key=PASSPHRASE)
        spec = store.load_spec(["base", Source("phrased", key=PASSPHRASE)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENV_STORE_CONNECTION", connection)
    monkeypatch.setenv("ENV_STORE_LOAD", spec.encode())
    for name in ("HOST", "SPEC_WORD"):
        # Set first, so monkeypatch removes what load() writes after the test.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)

    environment = load(use_project=False, noinput=True)

    assert environment.variables() == {"HOST": "base", "SPEC_WORD": "w"}
    assert os.environ["SPEC_WORD"] == "w"
