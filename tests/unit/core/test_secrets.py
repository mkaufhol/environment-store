import dataclasses
from typing import cast

import pytest

from environment_store.core.errors import ValidationError
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret

_KEY = bytes(range(32))


def test_key_material_holds_exactly_32_bytes() -> None:
    assert KeyMaterial(key=_KEY).key == _KEY


@pytest.mark.parametrize("length", [0, 16, 31, 33, 64])
def test_key_material_rejects_other_lengths(length: int) -> None:
    with pytest.raises(ValidationError, match=f"exactly 32 bytes, got {length}"):
        KeyMaterial(key=b"k" * length)


def test_key_material_rejects_non_bytes() -> None:
    with pytest.raises(ValidationError, match="must be bytes"):
        KeyMaterial(key=cast("bytes", bytearray(32)))


def test_key_material_repr_and_str_are_redacted() -> None:
    key = KeyMaterial(key=b"\xab" * 32)

    for text in (repr(key), str(key), f"{key}", repr([key])):
        assert "KeyMaterial(<redacted>)" in text
        assert "\\xab" not in text


def test_key_material_is_immutable() -> None:
    key = KeyMaterial(key=_KEY)

    with pytest.raises(dataclasses.FrozenInstanceError):
        key.key = b"x" * 32  # ty: ignore[invalid-assignment] - asserting the runtime guard


def test_passphrase_holds_its_text() -> None:
    assert Passphrase(text="correct horse").text == "correct horse"


def test_passphrase_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        Passphrase(text="")


def test_passphrase_rejects_non_strings() -> None:
    with pytest.raises(ValidationError, match="must be a string"):
        Passphrase(text=cast("str", b"secret"))


def test_passphrase_repr_and_str_are_redacted() -> None:
    passphrase = Passphrase(text="hunter2")

    for text in (repr(passphrase), str(passphrase), f"{passphrase}", repr([passphrase])):
        assert "Passphrase(<redacted>)" in text
        assert "hunter2" not in text


def test_secret_alias_covers_both_kinds() -> None:
    secrets: list[Secret] = [KeyMaterial(key=_KEY), Passphrase(text="x")]

    assert [type(secret).__name__ for secret in secrets] == ["KeyMaterial", "Passphrase"]
