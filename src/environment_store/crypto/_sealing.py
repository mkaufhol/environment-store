"""Opening and sealing store records for `StoreService`.

Private helpers of the service: which key goes with a store, its plaintext variables, and the
next record to write, sealed with a fresh nonce or plain.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, cast

from environment_store.core.errors import (
    KeyModeMismatchError,
    KeyRequiredError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode, StoreRecord
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.aead import open_sealed, seal
from environment_store.crypto.kdf import derive_key
from environment_store.crypto.keyfile import looks_like_key_file, parse_key, passphrase_from_text

__all__ = [
    "Encryption",
    "Opened",
    "Sealing",
    "copy_sealing",
    "new_sealing",
    "not_encrypted_message",
    "open_record",
    "seal_record",
    "secret_from_text",
    "validate_encryption",
]

type Encryption = Literal["same", "plain"] | Secret
"""Encryption of a copied store: as the source, plaintext, or with a new secret."""

_ENCRYPTION_CHOICES: Final[tuple[str, ...]] = ("same", "plain")


@dataclass(frozen=True, slots=True, kw_only=True)
class Sealing:
    """How a store is encrypted: its metadata and the key that goes with it."""

    meta: CipherMeta
    key: KeyMaterial = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Opened:
    """A store record together with its plaintext variables and its sealing, if encrypted."""

    record: StoreRecord
    variables: dict[str, str] = field(repr=False)
    sealing: Sealing | None


def not_encrypted_message(name: str) -> str:
    """Return the error message for a secret given for the plaintext store `name`."""
    return f"store {name!r} is not encrypted; it takes no key or passphrase"


def secret_from_text(name: str, meta: CipherMeta | None, text: str) -> Secret:
    """Interpret raw secret text by the store's key mode.

    Args:
        name: The store the secret is for.
        meta: The store's cipher metadata; `None` for a plaintext store.
        text: The raw text.

    Returns:
        The key of a `keyfile` store or the passphrase (one trailing newline stripped) of a
        `passphrase` store.

    Raises:
        NotEncryptedError: The store is not encrypted.
        InvalidKeyFileError: A `keyfile` store and the text is not a key file.
        KeyModeMismatchError: A `passphrase` store and the text is a key file.
        ValidationError: The passphrase is empty or not valid UTF-8.
    """
    if meta is None:
        raise NotEncryptedError(not_encrypted_message(name))
    if meta.mode is KeyMode.KEYFILE:
        return parse_key(text)
    if looks_like_key_file(text):
        message = f"store {name!r} uses a passphrase, but a key file was given"
        raise KeyModeMismatchError(message)
    return passphrase_from_text(text)


def validate_encryption(encryption: Encryption) -> None:
    """Check the encryption choice of a copy.

    Raises:
        ValidationError: It is neither `"same"`, `"plain"`, a key nor a passphrase.
    """
    if not isinstance(encryption, (KeyMaterial, Passphrase)) and (
        encryption not in _ENCRYPTION_CHOICES
    ):
        message = "encryption must be 'same', 'plain', a key or a passphrase"
        raise ValidationError(message)


def new_sealing(secret: Secret, kdf_params_factory: Callable[[], KdfParams]) -> Sealing:
    """Return the sealing for a new encryption with `secret`.

    Args:
        secret: A key (`keyfile` mode) or a passphrase (`passphrase` mode).
        kdf_params_factory: Source of fresh Argon2id parameters for a passphrase.

    Returns:
        The metadata and the key, derived with new parameters for a passphrase.
    """
    if isinstance(secret, KeyMaterial):
        return Sealing(meta=CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE), key=secret)
    params = kdf_params_factory()
    meta = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE, kdf=params)
    return Sealing(meta=meta, key=derive_key(secret, params))


def copy_sealing(
    encryption: Encryption, source: Sealing | None, kdf_params_factory: Callable[[], KdfParams]
) -> Sealing | None:
    """Return the sealing of a copy, for a choice checked by `validate_encryption`.

    Args:
        encryption: `"same"`, `"plain"` or a new secret.
        source: The source's sealing; `None` for a plaintext source.
        kdf_params_factory: Source of fresh Argon2id parameters for a new passphrase.

    Returns:
        The sealing of the copy; `None` for a plaintext copy.
    """
    if encryption == "same":
        # Same secret, same metadata: no second key derivation. Only the name in the
        # associated data changes, so the payload is sealed again.
        return source
    if encryption == "plain":
        return None
    return new_sealing(encryption, kdf_params_factory)


def open_record(record: StoreRecord, secret: Secret | None) -> Opened:
    """Decrypt a record if it is encrypted.

    Args:
        record: The record as read from the adapter.
        secret: Its key or passphrase; `None` for a plaintext store.

    Returns:
        The record with its variables and sealing.

    Raises:
        NotEncryptedError: A secret was given for a plaintext store.
        CryptoError: The secret is missing, of the wrong kind or wrong.
    """
    meta, ciphertext = record.cipher_meta, record.ciphertext
    if meta is None or ciphertext is None:
        if secret is not None:
            raise NotEncryptedError(not_encrypted_message(record.name))
        # A plaintext record always holds variables (StoreRecord invariant).
        return Opened(record=record, variables=dict(record.variables or {}), sealing=None)
    sealing = Sealing(meta=meta, key=_key_for(record.name, meta, secret))
    variables = open_sealed(ciphertext, store=record.name, meta=meta, key=sealing.key)
    return Opened(record=record, variables=variables, sealing=sealing)


def seal_record(  # noqa: PLR0913 - keyword-only mirror of the record fields
    *,
    name: str,
    variables: Mapping[str, str],
    sealing: Sealing | None,
    created_at: datetime,
    updated_at: datetime | None = None,
    revision: int = 1,
) -> StoreRecord:
    """Build a record, sealed with a fresh nonce or plain.

    Args:
        name: The store name; bound into the ciphertext.
        variables: The plaintext variables.
        sealing: How to encrypt them; `None` for a plaintext record.
        created_at: Creation time.
        updated_at: Time of the last write; defaults to `created_at`.
        revision: The revision; defaults to 1 (a new store).

    Returns:
        The new record.
    """
    if sealing is None:
        return StoreRecord.plain(
            name=name,
            variables=variables,
            created_at=created_at,
            updated_at=updated_at,
            revision=revision,
        )
    return StoreRecord.sealed(
        name=name,
        ciphertext=seal(variables, store=name, meta=sealing.meta, key=sealing.key),
        cipher_meta=sealing.meta,
        created_at=created_at,
        updated_at=updated_at,
        revision=revision,
    )


def _key_for(name: str, meta: CipherMeta, secret: Secret | None) -> KeyMaterial:
    if secret is None:
        raise KeyRequiredError.for_store(name)
    if meta.mode is KeyMode.KEYFILE:
        if not isinstance(secret, KeyMaterial):
            message = f"store {name!r} is encrypted with a key file, but a passphrase was given"
            raise KeyModeMismatchError(message)
        return secret
    if not isinstance(secret, Passphrase):
        message = f"store {name!r} is encrypted with a passphrase, but a key file was given"
        raise KeyModeMismatchError(message)
    # Passphrase mode always carries KDF parameters (CipherMeta invariant).
    return derive_key(secret, cast("KdfParams", meta.kdf))
