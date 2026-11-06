"""Load sources of the public library: a store and, optionally, its key (spec §7.3, PD 12)."""

from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path

from environment_store.core.errors import ValidationError
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.core.validation import validate_store_name

__all__ = ["KeyInput", "Source", "check_key_input"]

type KeyInput = Path | KeyMaterial | Passphrase
"""A key as the library takes it: a key or passphrase file, a key, or a passphrase (PD 12).

A plain `str` is refused, because it could be a path or a passphrase.
"""


def check_key_input(key: object) -> KeyInput:
    """Check that a value is a `KeyInput`.

    Args:
        key: The value.

    Returns:
        The unchanged key.

    Raises:
        ValidationError: It is not a `Path`, `KeyMaterial` or `Passphrase`; a plain string
            gets a hint. The message never contains the value.
    """
    if isinstance(key, (Path, KeyMaterial, Passphrase)):
        return key
    message = (
        f"a key must be a Path, KeyMaterial or Passphrase, got {type(key).__name__}; a plain "
        "string is refused because it could be a path or a passphrase: use Path(...) or "
        "Passphrase(text=...)"
    )
    raise ValidationError(message)


@dataclass(frozen=True, slots=True)
class Source:
    """One store of a load list, with its key if it is encrypted.

    `Source("base_conf")` or `Source("customer_a", key=Path("./a.key"))`; the key is
    keyword-only.

    Attributes:
        name: The store name (D27).
        key: The store's key, or `None` for a plaintext store (or to be prompted).
    """

    name: str
    _: KW_ONLY
    key: KeyInput | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate the name and the key.

        Raises:
            ValidationError: Invalid store name, or a key of the wrong type.
        """
        validate_store_name(self.name)
        if self.key is not None:
            check_key_input(self.key)
