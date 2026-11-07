"""TUI error messages: the TUI's own hints in place of the library's (D47)."""

from pathlib import Path

import pytest

from environment_store.core.errors import (
    EnvironmentStoreError,
    InvalidKeyFileError,
    StoreNotFoundError,
    ValidationError,
    VariableExistsError,
)
from environment_store.crypto.keyfile import parse_key
from environment_store.formats.dotenv import DotenvValueError
from environment_store.library.files import OutputFileExistsError
from environment_store.tui.messages import message_for


def test_invalid_key_file_names_keygen() -> None:
    with pytest.raises(InvalidKeyFileError) as caught:
        parse_key("not a key")

    message = message_for(caught.value)
    assert message == f"{caught.value.detail}; create one with envs keygen"


def test_library_hint_without_a_tui_remedy_is_left_out() -> None:
    error = VariableExistsError(["A"], store="base")

    assert message_for(error) == error.detail


@pytest.mark.parametrize(
    "error",
    [StoreNotFoundError("store 'x' does not exist"), ValidationError("bad name")],
    ids=["not-found", "validation"],
)
def test_errors_without_a_hint_keep_their_message(error: EnvironmentStoreError) -> None:
    assert message_for(error) == str(error)


def test_an_existing_output_file_names_the_tui_remedy(tmp_path: Path) -> None:
    error = OutputFileExistsError(tmp_path / "out.env")

    assert message_for(error) == (
        f"output file '{tmp_path / 'out.env'}' already exists; export again and confirm "
        "replacing it"
    )


def test_a_refused_dotenv_value_names_the_other_formats() -> None:
    error = DotenvValueError("A", "contains '${'")

    assert message_for(error) == f"{error.detail}; choose the JSON or TOML format"
