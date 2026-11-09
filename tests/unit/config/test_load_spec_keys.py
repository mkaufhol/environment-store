"""Keys of existing stores from `ENV_STORE_LOAD`.

The load specification is an environment key source, like `ENV_STORE_KEY_<STORE>`: explicit
source > environment > project `[keys]` > prompt. A store that gets a key from both
environment variables is refused, because it is unclear which one is meant. Plaintext stores
ignore it, and nothing echoes it.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from environment_store.config.key_variables import (
    environment_key_source,
    has_environment_key,
    secret_from_environment,
)
from environment_store.config.load_spec import LoadSpec
from environment_store.config.secrets import KeyFile, KeySource, SecretInput, SecretResolver
from environment_store.core.errors import (
    ConfigurationError,
    KeyModeMismatchError,
    KeyRequiredError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.keyfile import format_key
from environment_store.service import StoreService
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter

KEY: Final = KeyMaterial(key=b"\x07" * 32)
SPEC_KEY: Final = KeyMaterial(key=b"\x08" * 32)
PASSPHRASE: Final = Passphrase(text="correct horse battery staple")
CANARY: Final = "do-not-echo-this-value"


class Inspector:
    """A `StoreInspector` on a `StoreService` that counts metadata reads."""

    service: StoreService
    reads: list[str]

    def __init__(self, service: StoreService) -> None:
        self.service = service
        self.reads = []

    def store_info(self, name: str) -> StoreInfo:
        self.reads.append(name)
        return self.service.adapter.read_store(name).info

    def parse_secret(self, name: str, text: str) -> Secret:
        return self.service.parse_secret(name, text)


class Prompter:
    """Answers every secret prompt with key text and records the questions."""

    asked: list[str]

    def __init__(self) -> None:
        self.asked = []

    def secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return format_key(KEY)

    def new_secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def confirm(self, question: str) -> bool:
        raise AssertionError(question)


@pytest.fixture
def inspector() -> Inspector:
    service = StoreService(MemoryAdapter(), kdf_params_factory=CheapKdf())
    service.create_store("plain")
    service.create_store("keyed", secret=KEY)
    service.create_store("phrased", secret=PASSPHRASE)
    return Inspector(service)


def _spec(**keys: Secret) -> str:
    return LoadSpec(stores=("plain", "keyed", "phrased"), keys=keys).encode()


def _resolver(
    inspector: Inspector, environ: Mapping[str, str], *, prompter: Prompter | None = None
) -> SecretResolver:
    secret_input = SecretInput(
        read_stdin=lambda: format_key(KEY).encode(),
        stdin_is_tty=prompter is not None,
        prompter=prompter,
        environ=environ,
    )
    return SecretResolver(inspector, secret_input)


# --- reading keys  --------------------------------------------------------------------------------


def test_a_keyfile_store_takes_its_key_from_the_spec(inspector: Inspector) -> None:
    environ = {"ENV_STORE_LOAD": _spec(keyed=KEY)}

    assert _resolver(inspector, environ).existing("keyed", None) == KEY


def test_a_passphrase_store_takes_its_passphrase_from_the_spec(inspector: Inspector) -> None:
    environ = {"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}

    assert _resolver(inspector, environ).existing("phrased", None) == PASSPHRASE


def test_the_library_helper_reads_the_spec(inspector: Inspector) -> None:
    environ = {"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}

    assert secret_from_environment(inspector, "phrased", environ) == PASSPHRASE


@pytest.mark.parametrize(
    ("store", "secret", "message"),
    [
        (
            "phrased",
            KEY,
            "ENV_STORE_LOAD holds key text for store 'phrased', which uses a passphrase",
        ),
        (
            "keyed",
            Passphrase(text=CANARY),
            "ENV_STORE_LOAD holds a passphrase for store 'keyed', which uses a key file",
        ),
    ],
)
def test_a_secret_of_the_wrong_kind_is_refused_without_echoing_it(
    inspector: Inspector, store: str, secret: Secret, message: str
) -> None:
    environ = {"ENV_STORE_LOAD": _spec(**{store: secret})}

    with pytest.raises(KeyModeMismatchError) as caught:
        _resolver(inspector, environ).existing(store, None)

    assert str(caught.value) == message
    assert CANARY not in str(caught.value)


def test_a_store_with_a_key_in_both_variables_is_refused(inspector: Inspector) -> None:
    environ = {
        "ENV_STORE_KEY_KEYED": CANARY,
        "ENV_STORE_LOAD": _spec(keyed=Passphrase(text=CANARY)),
    }

    with pytest.raises(ValidationError) as caught:
        _resolver(inspector, environ).existing("keyed", None)

    message = str(caught.value)
    assert "store 'keyed' gets a key from both ENV_STORE_KEY_KEYED and ENV_STORE_LOAD" in message
    assert CANARY not in message


def test_the_library_helper_refuses_a_key_in_both_variables(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_KEYED": format_key(KEY), "ENV_STORE_LOAD": _spec(keyed=KEY)}

    with pytest.raises(ValidationError, match="from both"):
        secret_from_environment(inspector, "keyed", environ)


def test_the_two_variables_may_give_keys_for_different_stores(inspector: Inspector) -> None:
    environ = {
        "ENV_STORE_KEY_KEYED": format_key(KEY),
        "ENV_STORE_LOAD": _spec(phrased=PASSPHRASE),
    }
    resolver = _resolver(inspector, environ)

    assert resolver.existing("keyed", None) == KEY
    assert resolver.existing("phrased", None) == PASSPHRASE


def test_an_explicit_source_wins_and_skips_the_conflict(
    inspector: Inspector, tmp_path: Path
) -> None:
    path = tmp_path / "k.key"
    path.write_text(format_key(KEY), encoding="utf-8")
    environ = {"ENV_STORE_KEY_KEYED": CANARY, "ENV_STORE_LOAD": _spec(keyed=SPEC_KEY)}

    assert _resolver(inspector, environ).existing("keyed", KeyFile(path)) == KEY


def test_the_spec_wins_over_the_project_key_and_the_prompt(
    inspector: Inspector, tmp_path: Path
) -> None:
    project_key = tmp_path / "project.key"
    project_key.write_text(format_key(KEY), encoding="utf-8")
    prompter = Prompter()
    resolver = _resolver(inspector, {"ENV_STORE_LOAD": _spec(keyed=SPEC_KEY)}, prompter=prompter)

    assert resolver.existing("keyed", None, project_key=project_key) == SPEC_KEY
    assert prompter.asked == []


def test_a_store_without_a_key_in_the_spec_falls_through_to_the_prompt(
    inspector: Inspector,
) -> None:
    prompter = Prompter()
    resolver = _resolver(
        inspector, {"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}, prompter=prompter
    )

    assert resolver.existing("keyed", None) == KEY
    assert prompter.asked == ["Key or passphrase for store 'keyed': "]


def test_without_a_prompt_the_key_is_still_required(inspector: Inspector) -> None:
    with pytest.raises(KeyRequiredError):
        _resolver(inspector, {"ENV_STORE_LOAD": _spec()}).existing("keyed", None)


def test_a_plaintext_store_ignores_a_key_in_the_spec(inspector: Inspector) -> None:
    environ = {"ENV_STORE_LOAD": _spec(plain=KEY)}

    assert _resolver(inspector, environ).existing("plain", None) is None
    assert secret_from_environment(inspector, "plain", environ) is None


def test_metadata_is_read_only_when_the_spec_names_the_store(inspector: Inspector) -> None:
    environ = {"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}

    assert secret_from_environment(inspector, "keyed", environ) is None
    assert inspector.reads == []


def test_a_malformed_spec_fails_the_key_lookup(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_KEYED": format_key(KEY), "ENV_STORE_LOAD": CANARY}

    with pytest.raises(ConfigurationError, match=r"^ENV_STORE_LOAD is not a valid") as caught:
        _resolver(inspector, environ).existing("keyed", None)

    assert CANARY not in str(caught.value)


# --- where a key comes from  ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, None),
        ({"ENV_STORE_KEY_KEYED": "x"}, "ENV_STORE_KEY_KEYED"),
        ({"ENV_STORE_LOAD": _spec(keyed=KEY)}, "ENV_STORE_LOAD"),
        ({"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}, None),
        ({"ENV_STORE_LOAD": ""}, None),
    ],
)
def test_environment_key_source_names_the_variable(
    environ: dict[str, str], expected: str | None
) -> None:
    assert environment_key_source("keyed", environ) == expected
    assert has_environment_key("keyed", environ) is (expected is not None)


@pytest.mark.parametrize(
    ("source", "environ", "expected"),
    [
        (None, {"ENV_STORE_KEY_KEYED": "x"}, True),
        (None, {"ENV_STORE_LOAD": _spec(keyed=KEY)}, True),
        (KeyFile(Path("k.key")), {"ENV_STORE_LOAD": _spec(keyed=KEY)}, False),
        (None, {"ENV_STORE_LOAD": _spec(phrased=PASSPHRASE)}, False),
    ],
)
def test_uses_environment_key_counts_the_spec(
    inspector: Inspector, source: KeySource | None, environ: dict[str, str], *, expected: bool
) -> None:
    assert _resolver(inspector, environ).uses_environment_key("keyed", source) is expected
