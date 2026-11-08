import json
from typing import Final

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import DecryptionError, ValidationError
from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode
from environment_store.core.secrets import KeyMaterial
from environment_store.crypto import aead
from environment_store.crypto.aead import (
    NONCE_LENGTH,
    associated_data,
    encode_payload,
    open_sealed,
    seal,
)
from tests.support.strategies import cipher_metas, store_names, variable_maps

_KEY: Final = KeyMaterial(key=b"\x11" * 32)
_OTHER_KEY: Final = KeyMaterial(key=b"\x22" * 32)
_KEYFILE_META: Final = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE)
_PASSPHRASE_META: Final = CipherMeta(
    cipher=Cipher.AES256GCM,
    mode=KeyMode.PASSPHRASE,
    kdf=KdfParams(iterations=1, memory_kib=8, lanes=1, salt=bytes(16)),
)
_VARIABLES: Final = {"DB_HOST": "localhost", "DB_PASSWORD": "s3cr3t"}
_TAG_LENGTH: Final = 16


def _seal(variables: dict[str, str] | None = None) -> bytes:
    return seal(
        _VARIABLES if variables is None else variables,
        store="base",
        meta=_KEYFILE_META,
        key=_KEY,
    )


def test_nonce_is_96_bits() -> None:
    assert NONCE_LENGTH == 12


def test_payload_is_canonical_utf8_json_of_the_variables() -> None:
    payload = encode_payload({"b": "ü", "a": "x y"})

    assert payload == '{"variables":{"a":"x y","b":"ü"}}'.encode()


def test_associated_data_binds_store_format_version_and_cipher_metadata() -> None:
    data = associated_data(store="base", meta=_KEYFILE_META)

    assert data == b'{"cipher":{"cipher":"aes256gcm","mode":"keyfile"},"format":1,"store":"base"}'


def test_associated_data_includes_the_kdf_parameters() -> None:
    document = json.loads(associated_data(store="base", meta=_PASSPHRASE_META))

    assert document["cipher"] == _PASSPHRASE_META.to_json()


def test_seal_returns_nonce_then_aesgcm_ciphertext_with_tag() -> None:
    sealed = _seal()

    nonce, body = sealed[:NONCE_LENGTH], sealed[NONCE_LENGTH:]
    plaintext = AESGCM(_KEY.key).decrypt(
        nonce, body, associated_data(store="base", meta=_KEYFILE_META)
    )
    assert plaintext == encode_payload(_VARIABLES)
    assert len(body) == len(plaintext) + _TAG_LENGTH


def test_seal_uses_a_fresh_random_nonce_every_time() -> None:
    first, second = _seal(), _seal()

    assert first[:NONCE_LENGTH] != second[:NONCE_LENGTH]
    assert first != second


def test_seal_takes_the_nonce_from_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_token_bytes(length: int) -> bytes:
        calls.append(length)
        return b"\x05" * length

    monkeypatch.setattr(aead.secrets, "token_bytes", fake_token_bytes)

    assert _seal()[:NONCE_LENGTH] == b"\x05" * NONCE_LENGTH
    assert calls == [NONCE_LENGTH]


def test_seal_does_not_contain_names_or_values_in_clear() -> None:
    sealed = _seal()

    for text in ("DB_HOST", "DB_PASSWORD", "localhost", "s3cr3t"):
        assert text.encode() not in sealed


def test_seal_rejects_invalid_variables() -> None:
    with pytest.raises(ValidationError):
        _seal({"not valid": "x"})


def test_seal_rejects_an_invalid_store_name() -> None:
    with pytest.raises(ValidationError):
        seal(_VARIABLES, store="../x", meta=_KEYFILE_META, key=_KEY)


@given(variables=variable_maps(), store=store_names(), meta=cipher_metas())
def test_open_sealed_returns_what_seal_sealed(
    variables: dict[str, str], store: str, meta: CipherMeta
) -> None:
    sealed = seal(variables, store=store, meta=meta, key=_KEY)

    assert open_sealed(sealed, store=store, meta=meta, key=_KEY) == variables


def test_open_sealed_with_the_wrong_key_raises_decryption_error() -> None:
    with pytest.raises(DecryptionError, match="wrong key or passphrase"):
        open_sealed(_seal(), store="base", meta=_KEYFILE_META, key=_OTHER_KEY)


def test_open_sealed_for_another_store_name_raises_decryption_error() -> None:
    # A payload copied into another store must not decrypt: it is bound to the store name.
    with pytest.raises(DecryptionError):
        open_sealed(_seal(), store="other", meta=_KEYFILE_META, key=_KEY)


def test_open_sealed_with_changed_metadata_raises_decryption_error() -> None:
    with pytest.raises(DecryptionError):
        open_sealed(_seal(), store="base", meta=_PASSPHRASE_META, key=_KEY)


@pytest.mark.parametrize("position", [0, NONCE_LENGTH, NONCE_LENGTH + 3, -1])
def test_open_sealed_with_a_flipped_bit_raises_decryption_error(position: int) -> None:
    sealed = bytearray(_seal())
    sealed[position] ^= 0x01

    with pytest.raises(DecryptionError):
        open_sealed(bytes(sealed), store="base", meta=_KEYFILE_META, key=_KEY)


@pytest.mark.parametrize("length", [0, 1, NONCE_LENGTH, NONCE_LENGTH + _TAG_LENGTH - 1])
def test_open_sealed_with_a_truncated_payload_raises_decryption_error(length: int) -> None:
    with pytest.raises(DecryptionError):
        open_sealed(_seal()[:length], store="base", meta=_KEYFILE_META, key=_KEY)


def _seal_raw(plaintext: bytes) -> bytes:
    nonce = b"\x00" * NONCE_LENGTH
    body = AESGCM(_KEY.key).encrypt(
        nonce, plaintext, associated_data(store="base", meta=_KEYFILE_META)
    )
    return nonce + body


@pytest.mark.parametrize(
    "plaintext",
    [
        b"\xff\xfe",
        b"not json",
        b'["variables"]',
        b"{}",
        b'{"variables":{"A":"x"},"extra":1}',
        b'{"variables":["A"]}',
        b'{"variables":{"A":1}}',
        b'{"variables":{"not valid":"x"}}',
        b'{"variables":{"A":"nul\\u0000"}}',
        b'{"variables":{"A":"x","A":"y"}}',
    ],
)
def test_open_sealed_with_a_malformed_payload_raises_decryption_error(plaintext: bytes) -> None:
    with pytest.raises(DecryptionError, match="cannot decrypt"):
        open_sealed(_seal_raw(plaintext), store="base", meta=_KEYFILE_META, key=_KEY)


def test_open_sealed_accepts_a_valid_handmade_payload() -> None:
    sealed = _seal_raw(b'{"variables":{"A":"x"}}')

    assert open_sealed(sealed, store="base", meta=_KEYFILE_META, key=_KEY) == {"A": "x"}


@given(st.binary(max_size=64))
def test_open_sealed_never_raises_anything_but_decryption_error(data: bytes) -> None:
    with pytest.raises(DecryptionError):
        open_sealed(data, store="base", meta=_KEYFILE_META, key=_KEY)


def test_decryption_error_message_never_contains_secrets() -> None:
    sealed = _seal_raw(b'{"variables":{"A":"topsecret","bad name":"x"}}')

    with pytest.raises(DecryptionError) as excinfo:
        open_sealed(sealed, store="base", meta=_KEYFILE_META, key=_KEY)

    message = str(excinfo.value)
    assert "topsecret" not in message
    assert "bad name" not in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_wrong_key_error_hides_the_underlying_exception() -> None:
    with pytest.raises(DecryptionError) as excinfo:
        open_sealed(_seal(), store="base", meta=_KEYFILE_META, key=_OTHER_KEY)

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__
