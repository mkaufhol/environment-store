"""The store service: every store and variable operation, implemented once (spec §4, §6).

`StoreService` sits between the frontends (library, CLI, TUI) and an `Adapter`. It validates
every input before it touches the adapter, decrypts and re-encrypts encrypted stores (adapters
never see their plaintext, spec §4.4) and writes with the optimistic revision check (D7).
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, cast

from environment_store.core.adapter import Adapter
from environment_store.core.clock import Clock, utc_now
from environment_store.core.errors import (
    AlreadyEncryptedError,
    ConcurrentModificationError,
    KeyModeMismatchError,
    KeyRequiredError,
    NotEncryptedError,
    ValidationError,
    VariableExistsError,
    VariableNotFoundError,
)
from environment_store.core.models import (
    Cipher,
    CipherMeta,
    KdfParams,
    KeyMode,
    Source,
    StoreInfo,
    StoreRecord,
)
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.core.validation import (
    validate_store_name,
    validate_variable_name,
    validate_variables,
)
from environment_store.crypto.aead import open_sealed, seal
from environment_store.crypto.kdf import derive_key, new_kdf_params
from environment_store.crypto.keyfile import looks_like_key_file, parse_key, passphrase_from_text

__all__ = ["Encryption", "StoreService"]

type Encryption = Literal["same", "plain"] | Secret
"""Encryption of a copied store: as the source, plaintext, or with a new secret."""

_ENCRYPTION_CHOICES: Final[tuple[str, ...]] = ("same", "plain")


@dataclass(frozen=True, slots=True, kw_only=True)
class _Sealing:
    """How a store is encrypted: its metadata and the key that goes with it."""

    meta: CipherMeta
    key: KeyMaterial = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class _Opened:
    """A store record together with its plaintext variables and its sealing, if encrypted."""

    record: StoreRecord
    variables: dict[str, str] = field(repr=False)
    sealing: _Sealing | None


class StoreService:
    """All operations on stores and their variables, on top of one adapter.

    Every method validates every store name it receives before it touches the adapter.
    Encrypted stores need their secret for every content operation: without one,
    `KeyRequiredError`; a secret for a plaintext store, `NotEncryptedError`; a secret of the
    wrong kind, `KeyModeMismatchError`; a wrong secret, `DecryptionError`.

    Every write is read, modify, seal with a fresh nonce, then `write_store` with the revision
    that was read, so a concurrent change raises `ConcurrentModificationError` (D7).
    """

    _adapter: Adapter
    _clock: Clock
    _kdf_params_factory: Callable[[], KdfParams]

    def __init__(
        self,
        adapter: Adapter,
        *,
        clock: Clock = utc_now,
        kdf_params_factory: Callable[[], KdfParams] = new_kdf_params,
    ) -> None:
        """Create the service.

        Args:
            adapter: The backend; the caller owns it and closes it.
            clock: Source of the current UTC time for timestamps.
            kdf_params_factory: Source of Argon2id parameters (with a fresh salt) for new
                passphrase encryptions; tests inject cheap parameters.
        """
        self._adapter = adapter
        self._clock = clock
        self._kdf_params_factory = kdf_params_factory

    @property
    def adapter(self) -> Adapter:
        """The backend this service works on."""
        return self._adapter

    # --- stores --------------------------------------------------------------------------------

    def list_stores(self) -> list[StoreInfo]:
        """List every store; needs no key.

        Returns:
            One entry per store, sorted by name.
        """
        return self._adapter.list_stores()

    def create_store(self, name: str, *, secret: Secret | None = None) -> StoreInfo:
        """Create an empty store.

        Args:
            name: The new store's name.
            secret: `None` for a plaintext store, a key for `keyfile` mode or a passphrase for
                `passphrase` mode.

        Returns:
            The new store's listing entry.

        Raises:
            ValidationError: The name is invalid.
            StoreExistsError: The store exists already.
        """
        validate_store_name(name)
        sealing = None if secret is None else self._new_sealing(secret)
        record = self._new_record(name, {}, sealing)
        self._adapter.create_store(record)
        return record.info

    def delete_store(self, name: str) -> None:
        """Delete a store; needs no key, also for encrypted stores (D21).

        Args:
            name: The store name.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
        """
        validate_store_name(name)
        self._adapter.delete_store(name)

    def parse_secret(self, name: str, text: str) -> Secret:
        """Interpret raw secret text (from `-k` file, stdin or prompt) by the store's mode (D3).

        Args:
            name: The store the secret is for.
            text: The raw text.

        Returns:
            The key of a `keyfile` store or the passphrase (one trailing newline stripped) of a
            `passphrase` store.

        Raises:
            ValidationError: The name is invalid or the passphrase is empty.
            StoreNotFoundError: The store does not exist.
            NotEncryptedError: The store is not encrypted.
            InvalidKeyFileError: A `keyfile` store and the text is not a key file.
            KeyModeMismatchError: A `passphrase` store and the text is a key file.
        """
        validate_store_name(name)
        meta = self._adapter.read_store(name).cipher_meta
        if meta is None:
            raise NotEncryptedError(_not_encrypted_message(name))
        if meta.mode is KeyMode.KEYFILE:
            return parse_key(text)
        if looks_like_key_file(text):
            message = f"store {name!r} uses a passphrase, but a key file was given"
            raise KeyModeMismatchError(message)
        return passphrase_from_text(text)

    # --- variables -----------------------------------------------------------------------------

    def read_variables(self, name: str, *, secret: Secret | None = None) -> dict[str, str]:
        """Read all variables of a store.

        Args:
            name: The store name.
            secret: The store's key or passphrase; `None` for a plaintext store.

        Returns:
            A new dict of the variables.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
            CryptoError: The secret is missing, of the wrong kind or wrong.
            NotEncryptedError: A secret was given for a plaintext store.
        """
        validate_store_name(name)
        return self._open(name, secret).variables

    def set_variables(
        self,
        name: str,
        values: Mapping[str, str],
        *,
        secret: Secret | None = None,
        overwrite: bool = False,
    ) -> None:
        """Set one or more variables in a single write (D18).

        Args:
            name: The store name.
            values: The variables to set; at least one.
            secret: The store's key or passphrase; `None` for a plaintext store.
            overwrite: Replace variables that exist already.

        Raises:
            ValidationError: Invalid name, no values, or an invalid variable name or value.
            StoreNotFoundError: The store does not exist.
            VariableExistsError: Without `overwrite`, some variables exist; lists all of them
                and nothing is written.
            CryptoError: The secret is missing, of the wrong kind or wrong.
            NotEncryptedError: A secret was given for a plaintext store.
            ConcurrentModificationError: The store changed since it was read.
        """
        validate_store_name(name)
        checked = validate_variables(values)
        if not checked:
            message = "no variables to set"
            raise ValidationError(message)
        opened = self._open(name, secret)
        if not overwrite:
            conflicts = [variable for variable in checked if variable in opened.variables]
            if conflicts:
                raise VariableExistsError(conflicts, store=name)
        self._write(opened, opened.variables | checked, opened.sealing)

    def delete_variables(
        self, name: str, names: Collection[str], *, secret: Secret | None = None
    ) -> None:
        """Delete one or more variables in a single write.

        Args:
            name: The store name.
            names: The variable names; at least one, duplicates are ignored.
            secret: The store's key or passphrase; `None` for a plaintext store.

        Raises:
            ValidationError: Invalid store name, no names, a plain string instead of a
                collection of names, or an invalid variable name.
            StoreNotFoundError: The store does not exist.
            VariableNotFoundError: Some variables do not exist; lists all of them and nothing
                is written.
            CryptoError: The secret is missing, of the wrong kind or wrong.
            NotEncryptedError: A secret was given for a plaintext store.
            ConcurrentModificationError: The store changed since it was read.
        """
        validate_store_name(name)
        unique = _variable_names(names)
        opened = self._open(name, secret)
        missing = [variable for variable in unique if variable not in opened.variables]
        if missing:
            raise VariableNotFoundError(missing, store=name)
        remaining = {key: value for key, value in opened.variables.items() if key not in unique}
        self._write(opened, remaining, opened.sealing)

    # --- encryption lifecycle (D4) -------------------------------------------------------------

    def encrypt_store(self, name: str, *, secret: Secret) -> None:
        """Turn a plaintext store into an encrypted one; there is no way back (D4).

        Args:
            name: The store name.
            secret: The new key or passphrase.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
            AlreadyEncryptedError: The store is encrypted already.
            ConcurrentModificationError: The store changed since it was read.
        """
        validate_store_name(name)
        record = self._adapter.read_store(name)
        if record.encrypted:
            message = f"store {name!r} is already encrypted (use rekey to change its secret)"
            raise AlreadyEncryptedError(message)
        opened = self._unlock(record, None)
        self._write(opened, opened.variables, self._new_sealing(secret))

    def rekey_store(self, name: str, *, old: Secret, new: Secret) -> None:
        """Re-encrypt a store with a new secret; may switch the key mode (D4).

        A new passphrase always gets a new salt.

        Args:
            name: The store name.
            old: The current key or passphrase.
            new: The new key or passphrase.

        Raises:
            ValidationError: The name is invalid.
            StoreNotFoundError: The store does not exist.
            NotEncryptedError: The store is not encrypted.
            CryptoError: The old secret is of the wrong kind or wrong.
            ConcurrentModificationError: The store changed since it was read.
        """
        validate_store_name(name)
        record = self._adapter.read_store(name)
        if not record.encrypted:
            message = f"{_not_encrypted_message(name)} (use encrypt to encrypt it)"
            raise NotEncryptedError(message)
        opened = self._unlock(record, old)
        self._write(opened, opened.variables, self._new_sealing(new))

    # --- copy and move (D15) -------------------------------------------------------------------

    def copy_store(
        self,
        src: str,
        dst: str,
        *,
        secret: Secret | None = None,
        encryption: Encryption = "same",
        destination: "StoreService | None" = None,
    ) -> StoreInfo:
        """Copy a store under a new name or into another backend.

        The copy is always re-encrypted, because a ciphertext is bound to its store name (D5).

        Args:
            src: The source store.
            dst: The new store; may equal `src` only in another backend.
            secret: The source's key or passphrase; `None` for a plaintext store.
            encryption: `"same"` (default) encrypts the copy like the source, with the same
                secret; `"plain"` makes a plaintext copy (the way to decrypt, D4); a key or
                passphrase encrypts the copy with that secret.
            destination: The service of another backend; defaults to this one.

        Returns:
            The new store's listing entry.

        Raises:
            ValidationError: A name or the encryption choice is invalid.
            StoreNotFoundError: The source does not exist.
            StoreExistsError: The destination exists already; nothing is changed.
            CryptoError: The secret is missing, of the wrong kind or wrong.
            NotEncryptedError: A secret was given for a plaintext source.
        """
        _source, info = self._copy(src, dst, secret, encryption, destination)
        return info

    def move_store(
        self,
        src: str,
        dst: str,
        *,
        secret: Secret | None = None,
        encryption: Encryption = "same",
        destination: "StoreService | None" = None,
    ) -> StoreInfo:
        """Copy a store, then delete the source; a failure never leaves zero copies.

        Arguments and errors as for `copy_store`. If the source changes while it is being moved,
        the copy is removed again and the source stays.

        Returns:
            The new store's listing entry.

        Raises:
            ConcurrentModificationError: The source changed during the move.
        """
        source, info = self._copy(src, dst, secret, encryption, destination)
        target = self if destination is None else destination
        # Deleting does not check the revision: make sure no write is lost with the source.
        if self._adapter.read_store(src).revision != source.revision:
            target._adapter.delete_store(dst)
            message = f"store {src!r} was changed during the move; nothing was moved"
            raise ConcurrentModificationError(message)
        self._adapter.delete_store(src)
        return info

    # --- load ----------------------------------------------------------------------------------

    def load(self, sources: Sequence[Source]) -> list[tuple[str, dict[str, str]]]:
        """Read several stores for merging, in source order.

        Args:
            sources: The stores with their secrets, in load order; repeats are allowed.

        Returns:
            `(store name, variables)` per source, in the given order.

        Raises:
            ValidationError: A store name is invalid; checked for all before any read.
            StoreNotFoundError: A store does not exist.
            CryptoError: A secret is missing, of the wrong kind or wrong.
            NotEncryptedError: A secret was given for a plaintext store.
        """
        for source in sources:
            validate_store_name(source.name)
        return [
            (source.name, self._open(source.name, source.secret).variables) for source in sources
        ]

    # --- helpers -------------------------------------------------------------------------------

    def _open(self, name: str, secret: Secret | None) -> _Opened:
        return self._unlock(self._adapter.read_store(name), secret)

    def _unlock(self, record: StoreRecord, secret: Secret | None) -> _Opened:
        meta, ciphertext = record.cipher_meta, record.ciphertext
        if meta is None or ciphertext is None:
            if secret is not None:
                raise NotEncryptedError(_not_encrypted_message(record.name))
            # A plaintext record always holds variables (StoreRecord invariant).
            return _Opened(record=record, variables=dict(record.variables or {}), sealing=None)
        sealing = _Sealing(meta=meta, key=_key_for(record.name, meta, secret))
        variables = open_sealed(ciphertext, store=record.name, meta=meta, key=sealing.key)
        return _Opened(record=record, variables=variables, sealing=sealing)

    def _new_sealing(self, secret: Secret) -> _Sealing:
        if isinstance(secret, KeyMaterial):
            return _Sealing(
                meta=CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE), key=secret
            )
        params = self._kdf_params_factory()
        meta = CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE, kdf=params)
        return _Sealing(meta=meta, key=derive_key(secret, params))

    def _new_record(
        self, name: str, variables: Mapping[str, str], sealing: _Sealing | None
    ) -> StoreRecord:
        now = self._clock()
        if sealing is None:
            return StoreRecord.plain(name=name, variables=variables, created_at=now)
        return StoreRecord.sealed(
            name=name,
            ciphertext=seal(variables, store=name, meta=sealing.meta, key=sealing.key),
            cipher_meta=sealing.meta,
            created_at=now,
        )

    def _write(
        self, opened: _Opened, variables: Mapping[str, str], sealing: _Sealing | None
    ) -> None:
        record = opened.record
        # A store created on a machine whose clock is ahead must stay valid.
        updated_at = max(self._clock(), record.created_at)
        if sealing is None:
            new = StoreRecord.plain(
                name=record.name,
                variables=variables,
                created_at=record.created_at,
                updated_at=updated_at,
                revision=record.revision + 1,
            )
        else:
            new = StoreRecord.sealed(
                name=record.name,
                ciphertext=seal(variables, store=record.name, meta=sealing.meta, key=sealing.key),
                cipher_meta=sealing.meta,
                created_at=record.created_at,
                updated_at=updated_at,
                revision=record.revision + 1,
            )
        self._adapter.write_store(new, expected_revision=record.revision)

    def _copy(
        self,
        src: str,
        dst: str,
        secret: Secret | None,
        encryption: Encryption,
        destination: "StoreService | None",
    ) -> tuple[StoreRecord, StoreInfo]:
        validate_store_name(src)
        validate_store_name(dst)
        if not isinstance(encryption, (KeyMaterial, Passphrase)) and (
            encryption not in _ENCRYPTION_CHOICES
        ):
            message = "encryption must be 'same', 'plain', a key or a passphrase"
            raise ValidationError(message)
        target = self if destination is None else destination
        opened = self._open(src, secret)
        if encryption == "same":
            # Same secret, same metadata: no second key derivation. Only the name in the
            # associated data changes, so the payload is sealed again (D5).
            sealing = opened.sealing
        elif encryption == "plain":
            sealing = None
        else:
            sealing = target._new_sealing(encryption)
        record = target._new_record(dst, opened.variables, sealing)
        target._adapter.create_store(record)
        return opened.record, record.info


# --- module helpers ----------------------------------------------------------------------------


def _not_encrypted_message(name: str) -> str:
    return f"store {name!r} is not encrypted; it takes no key or passphrase"


def _key_for(name: str, meta: CipherMeta, secret: Secret | None) -> KeyMaterial:
    if secret is None:
        message = f"store {name!r} is encrypted ({meta.mode} mode): a key or passphrase is required"
        raise KeyRequiredError(message)
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


def _variable_names(names: Collection[str]) -> list[str]:
    if isinstance(names, str):
        message = "variable names must be a collection of names, not a single string"
        raise ValidationError(message)
    unique = list(dict.fromkeys(validate_variable_name(name) for name in names))
    if not unique:
        message = "no variables to delete"
        raise ValidationError(message)
    return unique
