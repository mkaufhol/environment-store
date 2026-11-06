import getpass
import io
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

from environment_store.config.project import PROJECT_FILE_NAME
from environment_store.config.settings import CredentialsInProjectFileWarning
from environment_store.core.errors import (
    ConfigurationError,
    KeyRequiredError,
    NotEncryptedError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.crypto.keyfile import format_key
from environment_store.library.environment import Environment
from environment_store.library.oneliner import load, load_with
from environment_store.library.sources import KeyInput
from environment_store.library.store import EnvironmentStore
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryBackend
from tests.unit.library.conftest import CONNECTION, KEY, OTHER_KEY, PASSPHRASE, RecordingOpener

_HIDDEN: Final = "hunter2-hidden"


class Prompts:
    """A `Prompter` with queued answers that records every question."""

    answers: list[str]
    asked: list[str]

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked = []

    def secret(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0)

    def new_secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def confirm(self, question: str) -> bool:
        raise AssertionError(question)


@pytest.fixture
def seeded(backend: MemoryBackend) -> MemoryBackend:
    with EnvironmentStore(
        CONNECTION,
        opener=lambda _url, setup: backend.open(setup=setup),
        kdf_params_factory=CheapKdf(),
    ) as store:
        store.create_store("base")
        store.set_many("base", {"HOST": "localhost", "PORT": "1"})
        store.create_store("staging")
        store.set("staging", "HOST", "staging")
        store.create_store("keyed", encrypt=True, key=KEY)
        store.set("keyed", "TOKEN", "t", key=KEY)
        store.create_store("phrased", encrypt=True, key=PASSPHRASE)
        store.set("phrased", "WORD", "w", key=PASSPHRASE)
    return backend


def _load(  # noqa: PLR0913 - mirrors the keyword-only signature under test
    tmp_path: Path,
    opener: RecordingOpener,
    *stores: str,
    target: dict[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    keys: Mapping[str, KeyInput] | None = None,
    interactive: bool = False,
    prompter: Prompts | None = None,
    noinput: bool = False,
    first_wins: bool = False,
    overwrite: bool = False,
    nested: bool = False,
    use_project: bool = True,
    connection: str | None = CONNECTION,
    uid: int | None = None,
) -> Environment:
    return load_with(
        stores,
        connection=connection,
        keys=keys,
        first_wins=first_wins,
        overwrite=overwrite,
        nested=nested,
        use_project=use_project,
        noinput=noinput,
        environ={} if environ is None else environ,
        cwd=tmp_path,
        boundary=tmp_path,
        uid=uid,
        interactive=interactive,
        prompter=Prompts() if prompter is None else prompter,
        target={} if target is None else target,
        opener=opener,
    )


def _project(directory: Path, text: str) -> None:
    (directory / PROJECT_FILE_NAME).write_text(text, encoding="utf-8")


def _key_file(directory: Path, name: str = "keyed.key") -> Path:
    path = directory / name
    path.write_text(format_key(KEY), encoding="ascii")
    return path


@pytest.mark.usefixtures("seeded")
def test_explicit_stores_are_merged_and_applied(tmp_path: Path, opener: RecordingOpener) -> None:
    target: dict[str, str] = {}

    environment = _load(tmp_path, opener, "base", "staging", target=target)

    assert environment.variables() == {"HOST": "staging", "PORT": "1"}
    assert target == {"HOST": "staging", "PORT": "1"}


@pytest.mark.usefixtures("seeded")
def test_store_is_closed_afterwards(tmp_path: Path, opener: RecordingOpener) -> None:
    _load(tmp_path, opener, "base")

    assert len(opener.opened) == 1
    assert opener.opened[0][2]._closed


@pytest.mark.usefixtures("seeded")
def test_project_stores_are_used_when_none_are_given(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    _project(tmp_path, 'stores = ["staging", "base"]\n')

    assert _load(tmp_path, opener).variables()["HOST"] == "localhost"


@pytest.mark.usefixtures("seeded")
def test_explicit_stores_replace_the_project_stores(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    _project(tmp_path, 'stores = ["missing"]\n')

    assert _load(tmp_path, opener, "staging").variables() == {"HOST": "staging"}


@pytest.mark.usefixtures("seeded")
def test_no_stores_at_all_is_a_configuration_error(tmp_path: Path, opener: RecordingOpener) -> None:
    with pytest.raises(ConfigurationError, match="stores"):
        _load(tmp_path, opener)
    assert opener.opened == []


def test_no_connection_is_a_configuration_error(tmp_path: Path, opener: RecordingOpener) -> None:
    with pytest.raises(ConfigurationError, match="ENV_STORE_CONNECTION"):
        _load(tmp_path, opener, "base", connection=None)


@pytest.mark.usefixtures("seeded")
def test_connection_from_the_environment(tmp_path: Path, opener: RecordingOpener) -> None:
    _load(
        tmp_path,
        opener,
        "base",
        connection=None,
        environ={"ENV_STORE_CONNECTION": "memory://env"},
    )

    assert opener.opened[0][0] == "memory://env"


@pytest.mark.usefixtures("seeded")
def test_first_wins_and_the_environment_setting(tmp_path: Path, opener: RecordingOpener) -> None:
    first = _load(tmp_path, opener, "base", "staging", first_wins=True)
    from_env = _load(
        tmp_path, opener, "base", "staging", environ={"ENV_STORE_ORDERED_OVERWRITE": "false"}
    )

    assert first.variables()["HOST"] == "localhost"
    assert from_env.variables()["HOST"] == "localhost"


@pytest.mark.usefixtures("seeded")
def test_existing_variables_are_kept_unless_overwrite(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    kept = {"HOST": "mine"}
    replaced = {"HOST": "mine"}

    _load(tmp_path, opener, "base", target=kept)
    _load(tmp_path, opener, "base", target=replaced, overwrite=True)

    assert kept["HOST"] == "mine"
    assert replaced["HOST"] == "localhost"


@pytest.mark.usefixtures("seeded")
def test_nested_applies_prefixed_names(tmp_path: Path, opener: RecordingOpener) -> None:
    target: dict[str, str] = {}

    _load(tmp_path, opener, "base", nested=True, target=target)

    assert target == {"BASE__HOST": "localhost", "BASE__PORT": "1"}


# --- keys --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("key", [KEY, None])
def test_explicit_keys_by_value_or_path(
    tmp_path: Path, opener: RecordingOpener, key: KeyInput | None
) -> None:
    # None stands for a key file.
    given = _key_file(tmp_path) if key is None else key

    environment = _load(tmp_path, opener, "keyed", keys={"keyed": given})

    assert environment.variables() == {"TOKEN": "t"}


@pytest.mark.usefixtures("seeded")
def test_project_key_paths_are_used(tmp_path: Path, opener: RecordingOpener) -> None:
    _key_file(tmp_path)
    _project(tmp_path, '[keys]\nkeyed = "keyed.key"\nunused = "nothing.key"\n')

    assert _load(tmp_path, opener, "keyed").variables() == {"TOKEN": "t"}


@pytest.mark.usefixtures("seeded")
def test_explicit_keys_beat_project_keys(tmp_path: Path, opener: RecordingOpener) -> None:
    _project(tmp_path, '[keys]\nkeyed = "missing.key"\n')

    assert _load(tmp_path, opener, "keyed", keys={"keyed": KEY}).variables() == {"TOKEN": "t"}


@pytest.mark.usefixtures("seeded")
def test_project_key_for_a_plaintext_store_is_an_error(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    _key_file(tmp_path)
    _project(tmp_path, '[keys]\nbase = "keyed.key"\n')

    with pytest.raises(NotEncryptedError):
        _load(tmp_path, opener, "base")


@pytest.mark.usefixtures("seeded")
def test_key_for_a_store_that_is_not_loaded_is_an_error(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    with pytest.raises(ValidationError, match="'other'"):
        _load(tmp_path, opener, "base", keys={"other": OTHER_KEY})


@pytest.mark.usefixtures("seeded")
def test_encrypted_store_is_prompted_once_when_interactive(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    prompts = Prompts(PASSPHRASE.text)

    environment = _load(
        tmp_path, opener, "phrased", "base", "phrased", interactive=True, prompter=prompts
    )

    assert environment.variables() == {"HOST": "localhost", "PORT": "1", "WORD": "w"}
    assert prompts.asked == ["Key or passphrase for store 'phrased': "]


@pytest.mark.usefixtures("seeded")
def test_missing_store_is_reported_before_prompting(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    prompts = Prompts(PASSPHRASE.text)

    with pytest.raises(StoreNotFoundError):
        _load(tmp_path, opener, "missing", "phrased", interactive=True, prompter=prompts)
    assert prompts.asked == []


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize(("interactive", "noinput"), [(False, False), (True, True)])
def test_encrypted_store_without_key_and_prompt_needs_a_key(
    tmp_path: Path,
    opener: RecordingOpener,
    interactive: bool,  # noqa: FBT001 - parametrised table column
    noinput: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    prompts = Prompts(PASSPHRASE.text)

    with pytest.raises(KeyRequiredError):
        _load(
            tmp_path, opener, "phrased", interactive=interactive, noinput=noinput, prompter=prompts
        )
    assert prompts.asked == []
    assert opener.opened[0][2]._closed


# --- warnings ----------------------------------------------------------------------------------


@pytest.mark.usefixtures("seeded")
def test_password_in_the_project_file_is_warned_about(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    _project(tmp_path, f'connection = "postgresql://u:{_HIDDEN}@host/db"\n')

    with pytest.warns(CredentialsInProjectFileWarning, match="ENV_STORE_CONNECTION") as caught:
        _load(tmp_path, opener, "base")

    assert all(_HIDDEN not in str(warning.message) for warning in caught)


@pytest.mark.usefixtures("seeded")
def test_untrusted_project_file_is_warned_about_and_ignored(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    _project(tmp_path, 'stores = ["base"]\n')

    with (
        pytest.warns(CredentialsInProjectFileWarning, match="ignoring project file"),
        pytest.raises(ConfigurationError, match="stores"),
    ):
        _load(tmp_path, opener, uid=os.geteuid() + 1)


@pytest.mark.usefixtures("seeded")
def test_no_project_skips_the_file(tmp_path: Path, opener: RecordingOpener) -> None:
    _project(tmp_path, 'stores = ["base"]\n')

    with pytest.raises(ConfigurationError, match="stores"):
        _load(tmp_path, opener, use_project=False)


# --- the public load() -------------------------------------------------------------------------


def _unset(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    # setenv first, so that monkeypatch restores the original state, absent or not.
    for name in names:
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _seed_files(directory: Path) -> str:
    connection = f"json://{directory / 'envs'}"
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf()) as store:
        store.create_store("base")
        store.set("base", "ENVSTORE_TEST_BASE", "b")
        store.create_store("phrased", encrypt=True, key=PASSPHRASE)
        store.set("phrased", "ENVSTORE_TEST_WORD", "w", key=PASSPHRASE)
    return connection


def test_public_load_resolves_the_project_and_prompts_on_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_files(tmp_path)
    _project(tmp_path, 'connection = "json://envs"\nstores = ["base", "phrased"]\n')
    project = tmp_path / "sub"
    project.mkdir()
    monkeypatch.chdir(project)
    _unset(
        monkeypatch,
        "ENV_STORE_CONNECTION",
        "ENV_STORE_ORDERED_OVERWRITE",
        "ENVSTORE_TEST_BASE",
        "ENVSTORE_TEST_WORD",
    )
    monkeypatch.setattr("sys.stdin", _Terminal())
    asked: list[str] = []

    def fake_getpass(prompt: str = "Password: ", stream: object = None) -> str:
        asked.append(prompt)
        return PASSPHRASE.text

    monkeypatch.setattr(getpass, "getpass", fake_getpass)

    environment = load()

    assert environment.variables() == {"ENVSTORE_TEST_BASE": "b", "ENVSTORE_TEST_WORD": "w"}
    assert os.environ["ENVSTORE_TEST_WORD"] == "w"
    assert asked == ["Key or passphrase for store 'phrased': "]


@pytest.mark.parametrize("stdin", [io.StringIO(), None])
def test_public_load_never_prompts_without_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin: io.StringIO | None
) -> None:
    connection = _seed_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENV_STORE_CONNECTION", connection)
    monkeypatch.setattr("sys.stdin", stdin)

    with pytest.raises(KeyRequiredError):
        load("phrased", use_project=False)


def test_public_load_with_noinput_never_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _seed_files(tmp_path)
    monkeypatch.setattr("sys.stdin", _Terminal())

    with pytest.raises(KeyRequiredError):
        load("phrased", connection=connection, use_project=False, noinput=True)


def test_public_load_passes_keys_and_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _seed_files(tmp_path)
    monkeypatch.setenv("ENVSTORE_TEST_BASE", "mine")
    monkeypatch.setenv("ENVSTORE_TEST_WORD", "mine")

    environment: Environment = load(
        "base",
        "phrased",
        connection=connection,
        keys={"phrased": PASSPHRASE},
        first_wins=True,
        overwrite=True,
        nested=False,
        use_project=False,
    )

    assert os.environ["ENVSTORE_TEST_BASE"] == "b"
    assert os.environ["ENVSTORE_TEST_WORD"] == "w"
    assert environment.order.value == "first_wins"
