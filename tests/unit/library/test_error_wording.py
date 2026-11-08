"""Library errors name library parameters, never CLI flags."""

import re
from pathlib import Path
from typing import Final

import pytest

from environment_store.config.settings import resolve_settings
from environment_store.core.errors import (
    ConfigurationError,
    EnvironmentStoreError,
    InvalidKeyFileError,
    KeyRequiredError,
    ValidationError,
    VariableExistsError,
    VariableNotFoundError,
)
from environment_store.core.merge import MergeOrder
from environment_store.crypto.keyfile import parse_key
from environment_store.formats import NestedInputError, dotenv, json_format
from environment_store.library.environment import Environment
from environment_store.library.files import OutputFileExistsError, write_output_file
from environment_store.library.oneliner import load_with
from environment_store.library.sources import check_key_input
from environment_store.library.store import EnvironmentStore
from tests.support.memory_adapter import MemoryBackend
from tests.unit.library.conftest import CONNECTION, KEY, RecordingOpener

# -o/--overwrite, --force, -t json, -k <path>, -c/--connection, --noinput, --nested, `envs …`
_CLI_FLAG: Final = re.compile(r"(?:^|[\s(/'\"])--?[a-z]|\benvs\b|\bkeygen\b")


def _assert_library_wording(error: EnvironmentStoreError) -> None:
    assert _CLI_FLAG.search(str(error)) is None, str(error)


def test_the_flag_pattern_finds_the_cli_wording() -> None:
    for text in ("use -o/--overwrite", "(--force)", "-t json", "with -k <path>", "envs run"):
        assert _CLI_FLAG.search(text) is not None, text
    for text in ("overwrite=True", "a-b", "key-file", "fmt='json'", "store 'x-y'"):
        assert _CLI_FLAG.search(text) is None, text


# --- core and service ------------------------------------------------------------------------


def test_existing_variables_name_the_overwrite_parameter(store: EnvironmentStore) -> None:
    store.create_store("base")
    store.set("base", "A", "1")

    with pytest.raises(VariableExistsError) as caught:
        store.set("base", "A", "2")

    assert "overwrite=True" in str(caught.value)
    _assert_library_wording(caught.value)


def test_get_of_one_missing_variable_is_singular_like_the_cli(store: EnvironmentStore) -> None:
    store.create_store("base")

    with pytest.raises(VariableNotFoundError) as caught:
        store.get("base", "NOPE")

    assert str(caught.value) == "variable 'NOPE' not found in store 'base'"


def test_missing_key_names_the_key_parameters(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(KeyRequiredError) as caught:
        store.variables("secret")

    assert str(caught.value) == str(KeyRequiredError.for_store("secret"))
    assert "key=" in str(caught.value)
    _assert_library_wording(caught.value)


@pytest.mark.parametrize(("interactive", "noinput"), [(False, False), (True, True)])
def test_load_without_a_key_has_the_same_wording_as_the_store_methods(
    tmp_path: Path,
    opener: RecordingOpener,
    backend: MemoryBackend,
    interactive: bool,  # noqa: FBT001 - parametrised table column
    noinput: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    with EnvironmentStore(CONNECTION, opener=lambda _url, setup: backend.open(setup=setup)) as s:
        s.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(KeyRequiredError) as caught:
        load_with(
            ["secret"],
            connection=CONNECTION,
            keys=None,
            first_wins=False,
            overwrite=False,
            nested=False,
            use_project=False,
            noinput=noinput,
            environ={},
            cwd=tmp_path,
            interactive=interactive,
            prompter=_NoPrompts(),
            target={},
            opener=opener,
        )

    assert str(caught.value) == str(KeyRequiredError.for_store("secret"))
    # A traceback prints the chained errors too: none of them may name a CLI flag.
    chained: BaseException | None = caught.value
    while chained is not None:
        assert _CLI_FLAG.search(str(chained)) is None, str(chained)
        chained = chained.__cause__ or chained.__context__


class _NoPrompts:
    def secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def new_secret(self, prompt: str) -> str:
        raise AssertionError(prompt)

    def confirm(self, question: str) -> bool:
        raise AssertionError(question)


def _load_with_connection(tmp_path: Path, connection: str | None) -> None:
    load_with(
        ["base"],
        connection=connection,
        keys=None,
        first_wins=False,
        overwrite=False,
        nested=False,
        use_project=False,
        noinput=True,
        environ={},
        cwd=tmp_path,
        interactive=False,
        prompter=_NoPrompts(),
        target={},
    )


def test_load_without_a_connection_names_the_connection_parameter(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        _load_with_connection(tmp_path, None)

    assert "connection=" in str(caught.value)
    assert "ENV_STORE_CONNECTION" in str(caught.value)
    _assert_library_wording(caught.value)


def test_load_with_an_empty_connection_names_the_connection_parameter(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        _load_with_connection(tmp_path, "")

    assert "connection" in str(caught.value)
    _assert_library_wording(caught.value)


def test_from_settings_without_a_connection_names_the_connection_parameter(
    tmp_path: Path, opener: RecordingOpener
) -> None:
    settings = resolve_settings(
        connection=None, use_project=False, environ={}, cwd=tmp_path, boundary=tmp_path
    )

    with pytest.raises(ConfigurationError) as caught:
        EnvironmentStore.from_settings(settings, opener=opener)

    assert "ENV_STORE_CONNECTION" in str(caught.value)
    _assert_library_wording(caught.value)
    assert opener.opened == []


# --- files and formats -----------------------------------------------------------------------


def test_existing_output_file_names_the_force_parameter(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("keep", encoding="utf-8")

    with pytest.raises(OutputFileExistsError) as caught:
        write_output_file(path, "A=1\n", force=False)

    assert isinstance(caught.value, ValidationError)
    assert caught.value.path == path
    assert "force=True" in str(caught.value)
    _assert_library_wording(caught.value)


def test_unknown_output_format_names_the_fmt_parameter(tmp_path: Path) -> None:
    environment = Environment(stores=(("base", {"A": "1"}),), order=MergeOrder.LAST_WINS)

    with pytest.raises(ValidationError) as caught:
        environment.to_file(tmp_path / "variables.txt")

    assert "fmt=" in str(caught.value)
    _assert_library_wording(caught.value)


@pytest.mark.parametrize("value", ["${HOME}", "it's $HOME"])
def test_dotenv_refusal_names_the_fmt_parameter(value: str) -> None:
    with pytest.raises(dotenv.DotenvValueError) as caught:
        dotenv.dumps({"TOKEN": value})

    assert isinstance(caught.value, ValidationError)
    assert caught.value.name == "TOKEN"
    assert "fmt='json'" in str(caught.value)
    assert value not in str(caught.value)
    _assert_library_wording(caught.value)


def test_nested_import_refusal_names_no_cli_flag() -> None:
    with pytest.raises(NestedInputError) as caught:
        json_format.loads('{"base": {"A": "1"}}')

    assert isinstance(caught.value, ValidationError)
    assert caught.value.detail == "JSON input has a nested object under 'base'"
    assert caught.value.name == "base"
    assert caught.value.hint is not None
    assert "nested=True" in caught.value.hint
    _assert_library_wording(caught.value)


# --- keys ------------------------------------------------------------------------------------


def test_invalid_key_text_names_the_library_key_functions() -> None:
    with pytest.raises(InvalidKeyFileError) as caught:
        parse_key("not a key")

    assert "generate_key_text()" in str(caught.value)
    _assert_library_wording(caught.value)


def test_plain_string_key_hint_names_parse_key_text() -> None:
    with pytest.raises(ValidationError) as caught:
        check_key_input("envstore-key-v1:abc")

    assert "parse_key_text(" in str(caught.value)
    _assert_library_wording(caught.value)
