import base64
import os
import stat
from pathlib import Path
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import BackendError, InvalidKeyFileError, ValidationError
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.crypto import keyfile
from environment_store.crypto.keyfile import (
    KEY_FILE_PREFIX,
    format_key,
    generate_key,
    looks_like_key_file,
    parse_key,
    passphrase_from_text,
    read_key_file,
    read_passphrase_file,
    write_key_file,
)

_KEY: Final[KeyMaterial] = KeyMaterial(key=bytes(range(32)))
_KEY_TEXT: Final[str] = "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8\n"


def test_key_file_prefix_names_the_format_version() -> None:
    assert KEY_FILE_PREFIX == "envstore-key-v1:"


def test_generate_key_returns_32_random_bytes() -> None:
    first, second = generate_key(), generate_key()

    assert len(first.key) == 32
    assert first != second


def test_generate_key_uses_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_token_bytes(length: int) -> bytes:
        calls.append(length)
        return b"\x01" * length

    monkeypatch.setattr(keyfile.secrets, "token_bytes", fake_token_bytes)

    assert generate_key() == KeyMaterial(key=b"\x01" * 32)
    assert calls == [32]


def test_format_key_is_prefix_unpadded_urlsafe_base64_and_newline() -> None:
    assert format_key(_KEY) == _KEY_TEXT


def test_format_key_uses_the_urlsafe_alphabet() -> None:
    text = format_key(KeyMaterial(key=b"\xfb\xff" * 16))

    assert "-" in text
    assert "_" in text
    assert "+" not in text
    assert "/" not in text
    assert "=" not in text


@given(st.binary(min_size=32, max_size=32))
def test_parse_key_reads_what_format_key_writes(raw: bytes) -> None:
    key = KeyMaterial(key=raw)

    assert parse_key(format_key(key)) == key


@pytest.mark.parametrize(
    "text",
    [
        _KEY_TEXT.rstrip("\n"),
        _KEY_TEXT.rstrip("\n") + "\r\n",
        "  " + _KEY_TEXT + "\n\n",
    ],
)
def test_parse_key_ignores_surrounding_whitespace(text: str) -> None:
    assert parse_key(text) == _KEY


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "correct horse battery staple",
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        "envstore-key-v2:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        "ENVSTORE-KEY-V1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        "envstore-key-v1:",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8A",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh+",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh/",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwd Hh8",
        "envstore-key-v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8\nsecond line",
        "envstore-key-v1:ÄAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
    ],
)
def test_parse_key_rejects_text_that_is_not_a_key_file(text: str) -> None:
    with pytest.raises(InvalidKeyFileError, match="not a valid key file"):
        parse_key(text)


def test_parse_key_rejects_non_canonical_trailing_bits() -> None:
    # 43 base64 characters carry 258 bits; the last two must be zero for 32 bytes.
    canonical = format_key(_KEY).strip()
    tampered = canonical[:-1] + "9"
    assert base64.urlsafe_b64decode(tampered.removeprefix(KEY_FILE_PREFIX) + "=") == _KEY.key

    with pytest.raises(InvalidKeyFileError, match="not a valid key file"):
        parse_key(tampered)


def test_parse_key_error_never_echoes_the_text() -> None:
    text = "envstore-key-v1:topsecretpassphrase"

    with pytest.raises(InvalidKeyFileError) as excinfo:
        parse_key(text)

    assert "topsecret" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_KEY_TEXT, True),
        ("  " + _KEY_TEXT, True),
        ("envstore-key-v1:garbage", True),
        ("correct horse battery staple\n", False),
        ("", False),
        ("my envstore-key-v1: passphrase", False),
    ],
)
def test_looks_like_key_file_checks_the_prefix(text: str, *, expected: bool) -> None:
    assert looks_like_key_file(text) is expected


def test_write_key_file_writes_the_key_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "store.key"

    write_key_file(path, _KEY)

    assert path.read_text(encoding="ascii") == _KEY_TEXT
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_key_file_keeps_0600_under_a_permissive_umask(tmp_path: Path) -> None:
    path = tmp_path / "store.key"
    previous = os.umask(0)
    try:
        write_key_file(path, _KEY)
    finally:
        os.umask(previous)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_key_file_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "store.key"
    path.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValidationError, match="already exists"):
        write_key_file(path, _KEY)

    assert path.read_text(encoding="utf-8") == "keep me"


def test_write_key_file_refuses_to_follow_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    link = tmp_path / "store.key"
    link.symlink_to(target)

    with pytest.raises(ValidationError, match="already exists"):
        write_key_file(link, _KEY)

    assert not target.exists()


def test_write_key_file_in_a_missing_directory_raises_backend_error(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "store.key"

    with pytest.raises(BackendError, match="cannot write key file") as excinfo:
        write_key_file(path, _KEY)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_write_key_file_removes_a_partial_file_when_writing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "store.key"

    def failing_fsync(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(keyfile.os, "fsync", failing_fsync)

    with pytest.raises(BackendError, match="cannot write key file"):
        write_key_file(path, _KEY)

    assert not path.exists()


def test_read_key_file_reads_a_written_key(tmp_path: Path) -> None:
    path = tmp_path / "store.key"
    write_key_file(path, _KEY)

    assert read_key_file(path) == _KEY


def test_read_key_file_rejects_a_passphrase_file(tmp_path: Path) -> None:
    path = tmp_path / "pass.txt"
    path.write_text("correct horse\n", encoding="utf-8")

    with pytest.raises(InvalidKeyFileError, match="not a valid key file"):
        read_key_file(path)


def test_read_key_file_rejects_binary_content(tmp_path: Path) -> None:
    path = tmp_path / "store.key"
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(InvalidKeyFileError, match="not a valid key file") as excinfo:
        read_key_file(path)

    # The UnicodeDecodeError holds the raw file content: it must not travel with the error.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


def test_read_key_file_that_is_missing_raises_backend_error(tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="cannot read key file") as excinfo:
        read_key_file(tmp_path / "missing.key")

    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hunter2", "hunter2"),
        ("hunter2\n", "hunter2"),
        ("hunter2\r\n", "hunter2"),
        ("hunter2\n\n", "hunter2\n"),
        (" spaced \n", " spaced "),
        ("multi\nline\n", "multi\nline"),
    ],
)
def test_passphrase_from_text_strips_exactly_one_trailing_newline(text: str, expected: str) -> None:
    assert passphrase_from_text(text) == Passphrase(text=expected)


@pytest.mark.parametrize("text", ["", "\n", "\r\n"])
def test_passphrase_from_text_rejects_an_empty_passphrase(text: str) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        passphrase_from_text(text)


def test_read_passphrase_file_strips_one_trailing_newline(tmp_path: Path) -> None:
    path = tmp_path / "pass.txt"
    path.write_text("correct horse \n\n", encoding="utf-8")

    assert read_passphrase_file(path) == Passphrase(text="correct horse \n")


def test_read_passphrase_file_reads_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pass.txt"
    path.write_bytes("pässwört ✓\n".encode())

    assert read_passphrase_file(path) == Passphrase(text="pässwört ✓")


def test_read_passphrase_file_rejects_non_utf8(tmp_path: Path) -> None:
    path = tmp_path / "pass.txt"
    path.write_bytes(b"\xff\xfe secret")

    with pytest.raises(ValidationError, match="not valid UTF-8") as excinfo:
        read_passphrase_file(path)

    assert "secret" not in str(excinfo.value)
    # The UnicodeDecodeError holds the raw file content: it must not travel with the error.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


def test_read_passphrase_file_that_is_missing_raises_backend_error(tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="cannot read passphrase file"):
        read_passphrase_file(tmp_path / "missing.txt")
