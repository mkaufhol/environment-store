import stat
from pathlib import Path

import pytest

from environment_store.core.errors import ValidationError
from environment_store.crypto.keyfile import parse_key, read_key_file
from environment_store.library.keys import generate_key_file, generate_key_text


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
