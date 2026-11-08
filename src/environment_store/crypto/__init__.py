"""Encryption: key files, Argon2id key derivation and AES-256-GCM sealing.

Imports nothing from Environment Store outside `environment_store.core`.
"""

from environment_store.crypto.aead import (
    NONCE_LENGTH,
    associated_data,
    encode_payload,
    open_sealed,
    seal,
)
from environment_store.crypto.kdf import SALT_LENGTH, derive_key, new_kdf_params
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

__all__ = [
    "KEY_FILE_PREFIX",
    "NONCE_LENGTH",
    "SALT_LENGTH",
    "associated_data",
    "derive_key",
    "encode_payload",
    "format_key",
    "generate_key",
    "looks_like_key_file",
    "new_kdf_params",
    "open_sealed",
    "parse_key",
    "passphrase_from_text",
    "read_key_file",
    "read_passphrase_file",
    "seal",
    "write_key_file",
]
