from pathlib import Path

import pytest

from environment_store.core.errors import ValidationError
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.library.sources import KeyInput, Source, check_key_input


def test_source_takes_the_store_name_positionally() -> None:
    source = Source("base_conf")

    assert source.name == "base_conf"
    assert source.key is None


@pytest.mark.parametrize(
    "key",
    [Path("a.key"), KeyMaterial(key=b"\x01" * 32), Passphrase(text="words")],
)
def test_source_takes_a_key_by_keyword(key: KeyInput) -> None:
    assert Source("a", key=key).key == key


def test_source_key_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        Source("a", Path("a.key"))  # ty: ignore[too-many-positional-arguments] - the point


def test_source_refuses_a_plain_string_key() -> None:
    with pytest.raises(ValidationError, match="plain string"):
        Source("a", key="secret words")  # ty: ignore[invalid-argument-type] - the point


def test_source_validates_the_store_name() -> None:
    with pytest.raises(ValidationError, match="store name"):
        Source("Not Valid")


def test_source_repr_hides_the_key() -> None:
    assert "words" not in repr(Source("a", key=Passphrase(text="words")))


@pytest.mark.parametrize("key", ["text", b"bytes", 1, None])
def test_check_key_input_refuses_everything_but_the_three_key_types(key: object) -> None:
    with pytest.raises(ValidationError, match="Path, KeyMaterial or Passphrase"):
        check_key_input(key)
