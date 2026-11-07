"""An existing store's key from `ENV_STORE_KEY_<STORE>` (spec §4.3, D53).

Precedence: explicit source > key variable > project `[keys]` > prompt. Collisions, empty or
invalid values, plaintext and unused stores, and the variable never being echoed.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from environment_store.config.key_variables import check_key_variables, secret_from_environment
from environment_store.config.secrets import (
    KeyFile,
    KeySource,
    KeyStdin,
    NewPassphrase,
    SecretInput,
    SecretResolver,
    resolve_new_secret,
)
from environment_store.core.errors import (
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.core.models import StoreInfo
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.keyfile import format_key
from environment_store.service import StoreService
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter

KEY: Final = KeyMaterial(key=b"\x07" * 32)
OTHER_KEY: Final = KeyMaterial(key=b"\x08" * 32)
FILE_KEY: Final = KeyMaterial(key=b"\x09" * 32)
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
    """Answers every secret prompt with `answer` and records the questions."""

    answer: str
    asked: list[str]

    def __init__(self, answer: str = "prompted") -> None:
        self.answer = answer
        self.asked = []

    def secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answer

    def new_secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answer

    def confirm(self, question: str) -> bool:
        self.asked.append(question)
        return False


@pytest.fixture
def inspector() -> Inspector:
    service = StoreService(MemoryAdapter(), kdf_params_factory=CheapKdf())
    service.create_store("plain")
    service.create_store("keyed", secret=KEY)
    service.create_store("phrased", secret=PASSPHRASE)
    service.create_store("my-app", secret=KEY)
    service.create_store("my_app", secret=OTHER_KEY)
    return Inspector(service)


def _resolver(
    inspector: Inspector,
    environ: Mapping[str, str],
    *,
    prompter: Prompter | None = None,
    stdin: bytes = b"",
) -> SecretResolver:
    secret_input = SecretInput(
        read_stdin=lambda: stdin,
        stdin_is_tty=prompter is not None,
        prompter=prompter,
        environ=environ,
    )
    return SecretResolver(inspector, secret_input)


def _key_file(tmp_path: Path, key: KeyMaterial) -> Path:
    path = tmp_path / "file.key"
    path.write_text(format_key(key), encoding="utf-8")
    return path


# --- reading the variable -------------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["", "\n", "\r\n"])
def test_key_text_for_a_keyfile_store(inspector: Inspector, ending: str) -> None:
    environ = {"ENV_STORE_KEY_KEYED": format_key(KEY).rstrip("\n") + ending}

    assert _resolver(inspector, environ).existing("keyed", None) == KEY


@pytest.mark.parametrize(("value", "expected"), [("pw", "pw"), ("pw\n", "pw"), ("pw\r\n", "pw")])
def test_passphrase_strips_exactly_one_trailing_newline(
    inspector: Inspector, value: str, expected: str
) -> None:
    inspector.service.create_store("nl", secret=Passphrase(text=expected))

    secret = _resolver(inspector, {"ENV_STORE_KEY_NL": value}).existing("nl", None)

    assert secret == Passphrase(text=expected)


def test_only_one_newline_is_stripped(inspector: Inspector) -> None:
    inspector.service.create_store("twice", secret=Passphrase(text="pw\n"))

    secret = _resolver(inspector, {"ENV_STORE_KEY_TWICE": "pw\n\n"}).existing("twice", None)

    assert secret == Passphrase(text="pw\n")


def test_the_variable_of_a_dashed_store_name_uses_underscores(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": format_key(KEY)}

    assert _resolver(inspector, environ).existing("my-app", None) == KEY


@pytest.mark.parametrize("value", ["", "\n", "\r\n"])
def test_a_set_but_empty_variable_is_a_key_source_error_naming_it(
    inspector: Inspector, value: str
) -> None:
    with pytest.raises(KeySourceError) as caught:
        _resolver(inspector, {"ENV_STORE_KEY_PHRASED": value}).existing("phrased", None)

    assert "ENV_STORE_KEY_PHRASED" in str(caught.value)
    assert "empty" in str(caught.value)


def test_invalid_key_text_is_an_invalid_key_file_error_without_the_value(
    inspector: Inspector,
) -> None:
    with pytest.raises(InvalidKeyFileError) as caught:
        _resolver(inspector, {"ENV_STORE_KEY_KEYED": CANARY}).existing("keyed", None)

    message = str(caught.value)
    assert "ENV_STORE_KEY_KEYED" in message
    assert "store 'keyed'" in message
    assert CANARY not in message
    assert caught.value.hint is not None  # the CLI replaces it with its keygen remedy (D47)


def test_key_text_for_a_passphrase_store_is_a_key_mode_mismatch_naming_the_variable(
    inspector: Inspector,
) -> None:
    environ = {"ENV_STORE_KEY_PHRASED": format_key(KEY)}

    with pytest.raises(KeyModeMismatchError) as caught:
        _resolver(inspector, environ).existing("phrased", None)

    message = str(caught.value)
    assert message == (
        "ENV_STORE_KEY_PHRASED holds key text, but store 'phrased' uses a passphrase"
    )
    assert "key file" not in message


def test_a_value_that_is_not_utf8_is_a_key_source_error(inspector: Inspector) -> None:
    # os.environ decodes undecodable bytes to lone surrogates (surrogateescape).
    environ = {"ENV_STORE_KEY_PHRASED": "pw\udcff"}

    with pytest.raises(KeySourceError, match="ENV_STORE_KEY_PHRASED is not valid UTF-8"):
        _resolver(inspector, environ).existing("phrased", None)


def test_a_wrong_key_is_returned_and_left_to_decryption(inspector: Inspector) -> None:
    # The resolver only parses; decrypting with it gives the usual DecryptionError.
    environ = {"ENV_STORE_KEY_KEYED": format_key(OTHER_KEY)}

    assert _resolver(inspector, environ).existing("keyed", None) == OTHER_KEY


# --- ignored --------------------------------------------------------------------------------------


def test_the_variable_of_a_plaintext_store_is_ignored(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_PLAIN": CANARY}

    assert _resolver(inspector, environ).existing("plain", None) is None


def test_an_empty_variable_of_a_plaintext_store_is_ignored(inspector: Inspector) -> None:
    assert _resolver(inspector, {"ENV_STORE_KEY_PLAIN": ""}).existing("plain", None) is None


def test_variables_of_other_stores_are_ignored(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_PHRASED": "", "ENV_STORE_KEY_OTHER": "x"}

    prompter = Prompter(format_key(KEY))

    assert _resolver(inspector, environ, prompter=prompter).existing("keyed", None) == KEY
    assert prompter.asked == ["Key or passphrase for store 'keyed': "]


def test_a_missing_store_is_reported_before_the_variable_is_read(inspector: Inspector) -> None:
    with pytest.raises(StoreNotFoundError):
        _resolver(inspector, {"ENV_STORE_KEY_MISSING": ""}).existing("missing", None)


def test_a_variable_with_a_lower_case_prefix_is_not_a_key_variable(inspector: Inspector) -> None:
    environ = {"env_store_key_keyed": format_key(KEY)}

    with pytest.raises(KeyRequiredError):
        _resolver(inspector, environ).existing("keyed", None)


# --- precedence -----------------------------------------------------------------------------------


type Given = tuple[bool, bool, bool, bool]
"""Which sources are present: explicit source, variable, project key, prompt."""


@pytest.mark.parametrize(
    ("given", "winner"),
    [
        ((True, True, True, True), "explicit"),
        ((True, False, False, False), "explicit"),
        ((False, True, True, True), "variable"),
        ((False, True, False, False), "variable"),
        ((False, False, True, True), "project"),
        ((False, False, True, False), "project"),
        ((False, False, False, True), "prompt"),
    ],
)
def test_precedence_explicit_then_variable_then_project_key_then_prompt(
    inspector: Inspector, tmp_path: Path, given: Given, winner: str
) -> None:
    explicit, variable, project, prompt = given
    candidates = {
        "explicit": KeyMaterial(key=b"\x11" * 32),
        "variable": KeyMaterial(key=b"\x12" * 32),
        "project": KeyMaterial(key=b"\x13" * 32),
        "prompt": KeyMaterial(key=b"\x14" * 32),
    }
    source: KeySource | None = KeyStdin() if explicit else None
    environ = {"ENV_STORE_KEY_KEYED": format_key(candidates["variable"])} if variable else {}
    project_key = _key_file(tmp_path, candidates["project"]) if project else None
    prompter = Prompter(format_key(candidates["prompt"])) if prompt else None
    resolver = _resolver(
        inspector, environ, prompter=prompter, stdin=format_key(candidates["explicit"]).encode()
    )

    secret = resolver.existing("keyed", source, project_key=project_key)

    assert secret == candidates[winner]
    if prompter is not None and winner != "prompt":
        assert prompter.asked == []


def test_without_any_source_and_no_prompt_a_key_is_required(inspector: Inspector) -> None:
    with pytest.raises(KeyRequiredError) as caught:
        _resolver(inspector, {}).existing("keyed", None)

    assert caught.value.hint is not None
    assert "ENV_STORE_KEY_KEYED" in caught.value.hint


def test_an_explicit_source_wins_over_a_broken_variable(
    inspector: Inspector, tmp_path: Path
) -> None:
    resolver = _resolver(inspector, {"ENV_STORE_KEY_KEYED": ""})

    assert resolver.existing("keyed", KeyFile(_key_file(tmp_path, KEY))) == KEY


def test_a_project_key_for_a_plaintext_store_is_still_refused(
    inspector: Inspector, tmp_path: Path
) -> None:
    with pytest.raises(NotEncryptedError):
        _resolver(inspector, {}).existing("plain", None, project_key=_key_file(tmp_path, KEY))


def test_a_project_key_file_that_cannot_be_read_is_a_key_source_error(
    inspector: Inspector, tmp_path: Path
) -> None:
    with pytest.raises(KeySourceError):
        _resolver(inspector, {}).existing("keyed", None, project_key=tmp_path / "missing.key")


@pytest.mark.parametrize(
    ("source", "environ", "expected"),
    [
        (None, {"ENV_STORE_KEY_KEYED": "x"}, True),
        (KeyStdin(), {"ENV_STORE_KEY_KEYED": "x"}, False),
        (None, {}, False),
        (None, {"ENV_STORE_KEY_OTHER": "x"}, False),
    ],
)
def test_uses_key_variable_tells_whether_the_variable_would_be_consulted(
    inspector: Inspector, source: KeySource | None, environ: dict[str, str], *, expected: bool
) -> None:
    assert _resolver(inspector, environ).uses_key_variable("keyed", source) is expected


# --- collisions -----------------------------------------------------------------------------------


def test_two_stores_of_one_variable_collide_when_it_is_set(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": CANARY}

    with pytest.raises(ValidationError) as caught:
        check_key_variables(inspector, ["my-app", "base", "my_app"], explicit=(), environ=environ)

    message = str(caught.value)
    assert "'my-app'" in message
    assert "'my_app'" in message
    assert "ENV_STORE_KEY_MY_APP" in message
    assert CANARY not in message


def test_an_empty_variable_collides_too(inspector: Inspector) -> None:
    with pytest.raises(ValidationError):
        check_key_variables(
            inspector, ["my-app", "my_app"], explicit=(), environ={"ENV_STORE_KEY_MY_APP": ""}
        )


def test_explicit_keys_for_both_stores_avoid_the_collision(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": CANARY}

    check_key_variables(
        inspector, ["my-app", "my_app"], explicit=("my-app", "my_app"), environ=environ
    )


def test_an_explicit_key_for_one_store_does_not_avoid_the_collision(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": CANARY}

    with pytest.raises(ValidationError):
        check_key_variables(inspector, ["my-app", "my_app"], explicit=("my-app",), environ=environ)


def test_an_unset_variable_never_collides(inspector: Inspector) -> None:
    check_key_variables(inspector, ["my-app", "my_app"], explicit=(), environ={})


def test_a_repeated_store_does_not_collide_with_itself(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": CANARY}

    check_key_variables(inspector, ["my-app", "my-app"], explicit=(), environ=environ)


def test_the_resolver_checks_collisions_with_its_environment(inspector: Inspector) -> None:
    resolver = _resolver(inspector, {"ENV_STORE_KEY_MY_APP": CANARY})

    with pytest.raises(ValidationError, match="ENV_STORE_KEY_MY_APP"):
        resolver.check_key_variables(["my-app", "my_app"], explicit=())
    resolver.check_key_variables(["my-app", "my_app"], explicit=("my-app", "my_app"))


def test_plaintext_stores_of_one_variable_never_collide(inspector: Inspector) -> None:
    # A plaintext store ignores the variable (D53), so it cannot be what the variable is for.
    inspector.service.create_store("a-b")
    inspector.service.create_store("a_b")

    check_key_variables(inspector, ["a-b", "a_b"], explicit=(), environ={"ENV_STORE_KEY_A_B": "x"})


def test_an_encrypted_and_a_plaintext_store_of_one_variable_do_not_collide(
    inspector: Inspector,
) -> None:
    inspector.service.create_store("a-b", secret=KEY)
    inspector.service.create_store("a_b")

    check_key_variables(inspector, ["a-b", "a_b"], explicit=(), environ={"ENV_STORE_KEY_A_B": "x"})


def test_a_collision_names_only_the_encrypted_stores(inspector: Inspector) -> None:
    inspector.service.create_store("x-y-z", secret=KEY)
    inspector.service.create_store("x_y-z")
    inspector.service.create_store("x-y_z", secret=PASSPHRASE)
    environ = {"ENV_STORE_KEY_X_Y_Z": CANARY}

    with pytest.raises(ValidationError) as caught:
        check_key_variables(inspector, ["x-y-z", "x_y-z", "x-y_z"], explicit=(), environ=environ)

    message = str(caught.value)
    assert message.startswith("encrypted stores 'x-y-z', 'x-y_z' all take their key from ")
    assert "x_y-z" not in message
    assert CANARY not in message


def test_metadata_is_read_only_for_a_possible_collision(inspector: Inspector) -> None:
    environ = {"ENV_STORE_KEY_MY_APP": CANARY, "ENV_STORE_KEY_KEYED": CANARY}

    check_key_variables(inspector, ["keyed", "my-app", "my_app"], explicit=(), environ={})
    check_key_variables(
        inspector, ["keyed", "my-app", "my_app"], explicit=("my-app", "my_app"), environ=environ
    )

    assert inspector.reads == []


# --- library helper -------------------------------------------------------------------------------


def test_secret_from_environment_reads_metadata_only_when_the_variable_is_set(
    inspector: Inspector,
) -> None:
    assert secret_from_environment(inspector, "keyed", {}) is None
    assert inspector.reads == []

    assert (
        secret_from_environment(inspector, "keyed", {"ENV_STORE_KEY_KEYED": format_key(KEY)}) == KEY
    )
    assert inspector.reads == ["keyed"]


def test_secret_from_environment_ignores_a_plaintext_store(inspector: Inspector) -> None:
    assert secret_from_environment(inspector, "plain", {"ENV_STORE_KEY_PLAIN": ""}) is None


# --- never for new secrets ------------------------------------------------------------------------


def test_a_new_passphrase_never_comes_from_the_variable(inspector: Inspector) -> None:
    secret_input = SecretInput(
        read_stdin=lambda: b"piped\n",
        stdin_is_tty=False,
        prompter=None,
        environ={"ENV_STORE_KEY_KEYED": "from-env", "ENV_STORE_KEY_NEW": "from-env"},
    )

    new = resolve_new_secret(NewPassphrase(), secret_input)

    assert new.secret == Passphrase(text="piped")
