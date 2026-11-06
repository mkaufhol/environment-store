import stat
from pathlib import Path

import pytest

from environment_store.config.prompt import GetpassPrompter
from environment_store.core.errors import InvalidKeyFileError, ValidationError
from environment_store.crypto.keyfile import parse_key, read_key_file
from environment_store.library.keys import generate_key_file, generate_key_text, parse_key_text
from environment_store.library.oneliner import load_with
from environment_store.library.store import EnvironmentStore
from tests.unit.library.conftest import CONNECTION, RecordingOpener


def test_generate_key_file_writes_a_key_file_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "a.key"

    generate_key_file(path)

    read_key_file(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_generate_key_file_accepts_a_string_path(tmp_path: Path) -> None:
    generate_key_file(str(tmp_path / "a.key"))

    assert (tmp_path / "a.key").is_file()


def test_generate_key_file_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "a.key"
    path.write_text("keep", encoding="utf-8")

    with pytest.raises(ValidationError, match="already exists"):
        generate_key_file(path)


def test_generate_key_text_is_a_new_key_each_time() -> None:
    first, second = generate_key_text(), generate_key_text()

    assert parse_key(first) != parse_key(second)
    assert first.endswith("\n")


# --- key text without a file (D47) -------------------------------------------------------------


def test_parse_key_text_reads_the_text_of_generate_key_text() -> None:
    text = generate_key_text()

    assert parse_key_text(text) == parse_key(text)
    assert parse_key_text(text.strip()) == parse_key(text)


def test_parse_key_text_refuses_other_text_without_echoing_it() -> None:
    with pytest.raises(InvalidKeyFileError) as caught:
        parse_key_text("hunter2-secret")

    assert "hunter2" not in str(caught.value)


def test_parsed_key_text_opens_a_store_and_loads_it(
    store: EnvironmentStore, tmp_path: Path, opener: RecordingOpener
) -> None:
    text = generate_key_text()
    store.create_store("secret", encrypt=True, key=parse_key_text(text))
    store.set("secret", "TOKEN", "t", key=parse_key_text(text))
    target: dict[str, str] = {}

    load_with(
        ["secret"],
        connection=CONNECTION,
        keys={"secret": parse_key_text(text)},
        first_wins=False,
        overwrite=False,
        nested=False,
        use_project=False,
        noinput=True,
        environ={},
        cwd=tmp_path,
        interactive=False,
        prompter=GetpassPrompter(),
        target=target,
        opener=opener,
    )

    assert store.get("secret", "TOKEN", key=parse_key_text(text)) == "t"
    assert target == {"TOKEN": "t"}
