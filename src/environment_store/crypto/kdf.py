"""Argon2id key derivation for passphrase stores.

The parameters are stored with each store (`KdfParams`), so they can be raised later without
breaking existing stores. Their upper bounds are enforced by `KdfParams` itself, so a tampered
store cannot force a huge computation.
"""

import secrets
from typing import Final

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from environment_store.core.models import KdfParams
from environment_store.core.secrets import KEY_LENGTH, KeyMaterial, Passphrase

__all__ = ["SALT_LENGTH", "derive_key", "new_kdf_params"]

SALT_LENGTH: Final[int] = 16
"""Length of a new random salt in bytes."""


def new_kdf_params() -> KdfParams:
    """Return parameters for a new passphrase store.

    Returns:
        The defaults (RFC 9106 second recommendation: `t=3`, `m=64 MiB`, `p=4`) with a
        fresh random 16-byte salt.
    """
    return KdfParams(salt=secrets.token_bytes(SALT_LENGTH))


def derive_key(passphrase: Passphrase, params: KdfParams) -> KeyMaterial:
    """Stretch a passphrase into a 256-bit key with Argon2id.

    Args:
        passphrase: The passphrase; encoded as UTF-8.
        params: The store's KDF parameters.

    Returns:
        The derived key.
    """
    kdf = Argon2id(
        salt=params.salt,
        length=KEY_LENGTH,
        iterations=params.iterations,
        lanes=params.lanes,
        memory_cost=params.memory_kib,
    )
    return KeyMaterial(key=kdf.derive(passphrase.text.encode("utf-8")))
