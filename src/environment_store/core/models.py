"""Domain model: store records, listing entries, cipher metadata and load sources.

All models are immutable value objects that validate their invariants on construction, so an
invalid record can neither be created by the core nor returned by an adapter.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final, Self

from environment_store.core._cipher import Cipher, CipherMeta, KdfParams, KeyMode
from environment_store.core.errors import ValidationError
from environment_store.core.secrets import Secret
from environment_store.core.validation import validate_store_name, validate_variables

__all__ = [
    "MAX_REVISION",
    "PAYLOAD_FORMAT_VERSION",
    "Cipher",
    "CipherMeta",
    "KdfParams",
    "KeyMode",
    "Source",
    "StoreInfo",
    "StoreRecord",
]

MAX_REVISION: Final[int] = 2**31 - 1
"""Largest revision of a store (D7): the SQL schema stores it as 32-bit `INTEGER` (spec §3.3.1)."""

PAYLOAD_FORMAT_VERSION: Final[int] = 1
"""Version of the encrypted payload format; part of the associated data (D5)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreInfo:
    """One entry of a store listing; needs no key.

    Attributes:
        name: The store name (D27).
        encrypted: Whether the store is encrypted.
        key_mode: The key mode; `None` for plaintext stores and for encrypted stores whose
            cipher metadata this version does not recognise.
        revision: The current revision (D7).
        created_at: Creation time, UTC.
        updated_at: Time of the last write, UTC.
    """

    name: str
    encrypted: bool
    key_mode: KeyMode | None
    revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Validate the entry.

        Raises:
            ValidationError: Invalid name, revision or timestamps, a non-bool `encrypted`, a
                `key_mode` that is neither a `KeyMode` nor `None`, or a key mode for a
                plaintext store.
        """
        validate_store_name(self.name)
        _check_revision(self.revision)
        _normalise_timestamps(self)
        if not isinstance(self.encrypted, bool):
            message = f"store {self.name!r}: encrypted must be a bool"
            raise ValidationError(message)
        if self.key_mode is not None and not isinstance(self.key_mode, KeyMode):
            message = f"store {self.name!r}: key_mode must be a KeyMode member or None"
            raise ValidationError(message)
        if not self.encrypted and self.key_mode is not None:
            message = f"store {self.name!r}: a plaintext store has no key mode"
            raise ValidationError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoreRecord:
    """A complete store as adapters persist it: opaque to them, plaintext or encrypted.

    Exactly one of `variables` (plaintext) or `ciphertext` + `cipher_meta` (encrypted) is set.

    Attributes:
        name: The store name (D27).
        revision: Revision counter, starting at 1 (D7).
        created_at: Creation time, UTC.
        updated_at: Time of the last write, UTC, not before `created_at`.
        variables: Plaintext variables (immutable, sorted by name in code point order), or `None`
            for an encrypted store.
        ciphertext: `nonce || ciphertext` of an encrypted store, or `None`.
        cipher_meta: Cipher metadata of an encrypted store, or `None`.
    """

    name: str
    revision: int
    created_at: datetime
    updated_at: datetime
    # Values may be secrets, and ciphertext is noise: neither belongs in a repr.
    variables: Mapping[str, str] | None = field(default=None, repr=False)
    ciphertext: bytes | None = field(default=None, repr=False)
    cipher_meta: CipherMeta | None = None

    def __post_init__(self) -> None:
        """Validate the record and freeze the variables.

        Raises:
            ValidationError: An invariant is violated.
        """
        validate_store_name(self.name)
        _check_revision(self.revision)
        _normalise_timestamps(self)
        if self.variables is not None:
            self._freeze_variables(self.variables)
        else:
            self._check_sealed()

    @classmethod
    def plain(
        cls,
        *,
        name: str,
        variables: Mapping[str, str],
        created_at: datetime,
        updated_at: datetime | None = None,
        revision: int = 1,
    ) -> Self:
        """Build a plaintext record.

        Args:
            name: The store name.
            variables: The variables; copied.
            created_at: Creation time.
            updated_at: Time of the last write; defaults to `created_at`.
            revision: The revision; defaults to 1 (a new store).

        Returns:
            The validated record.
        """
        return cls(
            name=name,
            revision=revision,
            created_at=created_at,
            updated_at=created_at if updated_at is None else updated_at,
            variables=variables,
        )

    @classmethod
    def sealed(  # noqa: PLR0913 - keyword-only mirror of the record fields
        cls,
        *,
        name: str,
        ciphertext: bytes,
        cipher_meta: CipherMeta,
        created_at: datetime,
        updated_at: datetime | None = None,
        revision: int = 1,
    ) -> Self:
        """Build an encrypted record.

        Args:
            name: The store name.
            ciphertext: `nonce || ciphertext`, opaque to adapters.
            cipher_meta: The cipher metadata.
            created_at: Creation time.
            updated_at: Time of the last write; defaults to `created_at`.
            revision: The revision; defaults to 1 (a new store).

        Returns:
            The validated record.
        """
        return cls(
            name=name,
            revision=revision,
            created_at=created_at,
            updated_at=created_at if updated_at is None else updated_at,
            ciphertext=ciphertext,
            cipher_meta=cipher_meta,
        )

    @property
    def encrypted(self) -> bool:
        """Whether the record holds ciphertext."""
        return self.ciphertext is not None

    @property
    def info(self) -> StoreInfo:
        """The listing entry of this record."""
        return StoreInfo(
            name=self.name,
            encrypted=self.encrypted,
            key_mode=None if self.cipher_meta is None else self.cipher_meta.mode,
            revision=self.revision,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def _freeze_variables(self, variables: Mapping[str, str]) -> None:
        if self.ciphertext is not None or self.cipher_meta is not None:
            message = (
                f"store {self.name!r}: a record holds variables or ciphertext and cipher_meta, "
                "not both"
            )
            raise ValidationError(message)
        if not isinstance(variables, Mapping):
            message = f"store {self.name!r}: variables must be a mapping"
            raise ValidationError(message)
        # Code point order, so that every backend returns the same order (JSONB reorders keys).
        ordered = dict(sorted(validate_variables(variables).items()))
        object.__setattr__(self, "variables", MappingProxyType(ordered))

    def _check_sealed(self) -> None:
        if self.ciphertext is None or self.cipher_meta is None:
            message = (
                f"store {self.name!r}: a record needs either variables or ciphertext and "
                "cipher_meta"
            )
            raise ValidationError(message)
        if not isinstance(self.ciphertext, bytes):
            message = f"store {self.name!r}: ciphertext must be bytes"
            raise ValidationError(message)
        if not isinstance(self.cipher_meta, CipherMeta):
            message = f"store {self.name!r}: cipher_meta must be CipherMeta"
            raise ValidationError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class Source:
    """One entry of a load list: a store and, if it is encrypted, its secret.

    Attributes:
        name: The store name (D27).
        secret: The key or passphrase, or `None` for a plaintext store.
    """

    name: str
    secret: Secret | None = None

    def __post_init__(self) -> None:
        """Validate the store name.

        Raises:
            ValidationError: The store name is invalid.
        """
        validate_store_name(self.name)


# --- helpers -----------------------------------------------------------------------------------


def _check_revision(revision: object) -> None:
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or not 1 <= revision <= MAX_REVISION
    ):
        message = f"revision must be an integer >= 1 and <= {MAX_REVISION}, got {revision!r}"
        raise ValidationError(message)


def _aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        message = f"{name} must be a timezone-aware datetime"
        raise ValidationError(message)
    try:
        return value.astimezone(UTC)
    except OverflowError as err:
        # E.g. 9999-12-31T23:59:59-01:00: the instant has no UTC `datetime`.
        message = f"{name} is out of range"
        raise ValidationError(message) from err


def _normalise_timestamps(model: StoreInfo | StoreRecord) -> None:
    created_at = _aware_utc(model.created_at, "created_at")
    updated_at = _aware_utc(model.updated_at, "updated_at")
    if created_at > updated_at:
        message = f"store {model.name!r}: created_at must not be after updated_at"
        raise ValidationError(message)
    # Frozen dataclass: normalising to UTC keeps the instant and gives adapters one form.
    object.__setattr__(model, "created_at", created_at)
    object.__setattr__(model, "updated_at", updated_at)
