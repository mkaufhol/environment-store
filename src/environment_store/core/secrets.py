"""Secret values: raw keys and passphrases with redacted representations.

Neither `repr` nor `str` ever shows the secret, so it cannot leak through logs, exception messages
or tracebacks.
"""

from dataclasses import dataclass, field
from typing import Final, override

from environment_store.core.errors import ValidationError

__all__ = ["KEY_LENGTH", "KeyMaterial", "Passphrase", "Secret"]

KEY_LENGTH: Final[int] = 32
"""Length of an AES-256 key in bytes."""


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class KeyMaterial:
    """A raw 256-bit key, from a key file or derived from a passphrase.

    Attributes:
        key: Exactly 32 bytes.
    """

    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Validate the key length.

        Raises:
            ValidationError: The key is not `bytes` of exactly 32 bytes.
        """
        if not isinstance(self.key, bytes):
            message = f"key material must be bytes, got {type(self.key).__name__}"
            raise ValidationError(message)
        if len(self.key) != KEY_LENGTH:
            message = f"key material must be exactly {KEY_LENGTH} bytes, got {len(self.key)}"
            raise ValidationError(message)

    @override
    def __repr__(self) -> str:
        return "KeyMaterial(<redacted>)"

    @override
    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class Passphrase:
    """A human passphrase, stretched with Argon2id before use.

    Attributes:
        text: The non-empty passphrase.
    """

    text: str = field(repr=False)

    def __post_init__(self) -> None:
        """Validate the passphrase.

        Raises:
            ValidationError: The passphrase is not a string, is empty or is not valid UTF-8
                (it has a lone surrogate); the message never contains the text.
        """
        if not isinstance(self.text, str):
            message = f"passphrase must be a string, got {type(self.text).__name__}"
            raise ValidationError(message)
        if not self.text:
            message = "passphrase must not be empty"
            raise ValidationError(message)
        try:
            self.text.encode("utf-8")
        except UnicodeEncodeError:
            message = "passphrase is not valid UTF-8 (it has a lone surrogate)"
            # Not chained: the encode error holds the whole passphrase.
            raise ValidationError(message) from None

    @override
    def __repr__(self) -> str:
        return "Passphrase(<redacted>)"

    @override
    def __str__(self) -> str:
        return self.__repr__()


type Secret = KeyMaterial | Passphrase
"""The secret of an encrypted store: a key (`keyfile` mode) or a passphrase (`passphrase` mode)."""
