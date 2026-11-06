"""AES-256-GCM sealing of store payloads (spec §4.1, §4.2, D1, D5).

The whole store is encrypted as one blob: the plaintext is the canonical JSON of
`{"variables": {...}}`, so no variable name or value leaks. The associated data binds the
ciphertext to the store name, the payload format version and the cipher metadata (D5): copying a
payload into another store or changing the metadata makes decryption fail.

A sealed payload is `nonce (12 random bytes) || AES-GCM ciphertext and 16-byte tag`.
"""

import json
import secrets
from collections.abc import Mapping
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from environment_store.core.errors import DecryptionError, EnvironmentStoreError
from environment_store.core.models import PAYLOAD_FORMAT_VERSION, CipherMeta
from environment_store.core.secrets import KeyMaterial
from environment_store.core.validation import validate_store_name, validate_variables

__all__ = ["NONCE_LENGTH", "associated_data", "encode_payload", "open_sealed", "seal"]

NONCE_LENGTH: Final[int] = 12
"""Length of the random GCM nonce in bytes (96 bits)."""

_TAG_LENGTH: Final[int] = 16


def encode_payload(variables: Mapping[str, str]) -> bytes:
    """Return the plaintext that is encrypted for a store.

    Args:
        variables: The store's variables.

    Returns:
        Canonical UTF-8 JSON of `{"variables": {...}}` (sorted keys, no whitespace).
    """
    return _canonical_json({"variables": dict(variables)})


def associated_data(*, store: str, meta: CipherMeta) -> bytes:
    """Return the authenticated data of a store's encryption (D5).

    Args:
        store: The store name.
        meta: The store's cipher metadata.

    Returns:
        Canonical UTF-8 JSON of `{"store", "format", "cipher"}`.
    """
    return _canonical_json(
        {"store": store, "format": PAYLOAD_FORMAT_VERSION, "cipher": meta.to_json()}
    )


def seal(variables: Mapping[str, str], *, store: str, meta: CipherMeta, key: KeyMaterial) -> bytes:
    """Encrypt a store's variables with a fresh random nonce.

    Args:
        variables: The variables; validated first.
        store: The store name, bound into the associated data.
        meta: The cipher metadata, bound into the associated data.
        key: The 256-bit key (from a key file or derived from the passphrase).

    Returns:
        `nonce || ciphertext and tag`.

    Raises:
        ValidationError: The store name or a variable is invalid.
    """
    validate_store_name(store)
    checked = validate_variables(variables)
    nonce = secrets.token_bytes(NONCE_LENGTH)
    body = AESGCM(key.key).encrypt(
        nonce, encode_payload(checked), associated_data(store=store, meta=meta)
    )
    return nonce + body


def open_sealed(
    ciphertext: bytes, *, store: str, meta: CipherMeta, key: KeyMaterial
) -> dict[str, str]:
    """Decrypt and validate a sealed payload.

    Args:
        ciphertext: `nonce || ciphertext and tag` as written by `seal`.
        store: The store name the payload belongs to.
        meta: The store's cipher metadata.
        key: The 256-bit key.

    Returns:
        The variables.

    Raises:
        DecryptionError: Wrong key, tampered data, another store name, changed metadata or a
            malformed payload. The message and the exception chain never reveal details.
    """
    message = (
        f"cannot decrypt store {store!r}: wrong key or passphrase, or the stored data was modified"
    )
    if len(ciphertext) < NONCE_LENGTH + _TAG_LENGTH:
        raise DecryptionError(message)
    nonce, body = ciphertext[:NONCE_LENGTH], ciphertext[NONCE_LENGTH:]
    try:
        plaintext = AESGCM(key.key).decrypt(nonce, body, associated_data(store=store, meta=meta))
    except InvalidTag:
        raise DecryptionError(message) from None
    variables = _decode_payload(plaintext)
    if variables is None:
        raise DecryptionError(message)
    return variables


def _decode_payload(plaintext: bytes) -> dict[str, str] | None:
    # Authenticated but malformed: only a writer holding the key can produce this. Details may
    # contain variable names (secret, D1), so they are dropped, not chained.
    try:
        document: object = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_unique_keys)
    except ValueError:  # UnicodeDecodeError, JSONDecodeError, duplicate keys
        return None
    if not isinstance(document, dict) or set(document) != {"variables"}:
        return None
    variables: object = document["variables"]
    if not isinstance(variables, dict):
        return None
    try:
        return validate_variables(variables)
    except EnvironmentStoreError:
        return None


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document = dict(pairs)
    if len(document) != len(pairs):
        message = "duplicate key"
        raise ValueError(message)
    return document


def _canonical_json(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
