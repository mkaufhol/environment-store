"""`envs rekey` and `envs encrypt`: give a store a new secret (spec §4.5, D4, D34).

Both need exactly one usable choice of `--new-key`, `--generate-key` and `--passphrase`; that
is checked before any key is read or asked for. The library call runs inside `keep_or_discard`
(PD 33): a generated key file is removed only if the store provably does not use it.
"""

from pathlib import Path
from typing import Final, cast

import typer

from environment_store.cli.key_options import parse_key_path
from environment_store.cli.options import (
    GenerateKeyOpt,
    NewKeyOpt,
    PassphraseOpt,
    StoreOpt,
    WriteKeyOpt,
)
from environment_store.cli.output import err
from environment_store.cli.secrets import existing_secret, keep_or_discard, new_secret
from environment_store.cli.state import get_state
from environment_store.config.secrets import NewSecret
from environment_store.core.errors import (
    AlreadyEncryptedError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.secrets import KeyMaterial
from environment_store.core.validation import validate_store_name

__all__ = ["encrypt", "rekey"]

_NEW_KEY_OPTION: Final = "--new-key"
_STDOUT_PATH: Final = Path("-")
_NO_FILE_PATH: Final = Path()


def rekey(  # noqa: PLR0913 - the options of spec §4.5
    ctx: typer.Context,
    *,
    store: StoreOpt,
    key: WriteKeyOpt = None,
    new_key: NewKeyOpt = None,
    generate: GenerateKeyOpt = None,
    passphrase: PassphraseOpt = False,
) -> None:
    """Re-encrypt a store with a new secret.

    The new key file or passphrase replaces the old one; passphrases get a new salt.
    """
    validate_store_name(store)
    _require_one(new_key=new_key, generate=generate, passphrase=passphrase)
    environment = get_state(ctx).open_store(ctx)
    old = existing_secret(ctx, store, key)
    if old is None:
        # Checked before a key file is generated or a new passphrase is asked for.
        message = f"store {store!r} is not encrypted: use 'envs encrypt -s {store}'"
        raise NotEncryptedError(message)
    new = _new(ctx, new_key=new_key, generate=generate, passphrase=passphrase)
    with keep_or_discard(new, target=store, store=environment, creates_target=False):
        environment.rekey_store(store, old=old, new=new.secret)
    err(f"rekeyed store '{store}' ({_mode(new)})")


def encrypt(
    ctx: typer.Context,
    *,
    store: StoreOpt,
    new_key: NewKeyOpt = None,
    generate: GenerateKeyOpt = None,
    passphrase: PassphraseOpt = False,
) -> None:
    """Encrypt a plaintext store.

    There is no way back in place; a plaintext copy is made with cp-store --plain.
    """
    validate_store_name(store)
    _require_one(new_key=new_key, generate=generate, passphrase=passphrase)
    environment = get_state(ctx).open_store(ctx)
    if environment.store_info(store).encrypted:
        # Checked before a key file is generated or a passphrase is asked for.
        message = f"store {store!r} is already encrypted: use 'envs rekey -s {store}'"
        raise AlreadyEncryptedError(message)
    new = _new(ctx, new_key=new_key, generate=generate, passphrase=passphrase)
    with keep_or_discard(new, target=store, store=environment, creates_target=False):
        environment.encrypt_store(store, key=new.secret)
    err(f"encrypted store '{store}' ({_mode(new)})")


def _require_one(*, new_key: str | None, generate: Path | None, passphrase: bool) -> None:
    # Before any prompt: the old key must not be asked for when the command cannot run.
    if new_key is None and generate is None and not passphrase:
        message = f"give the new secret: {_NEW_KEY_OPTION}, --generate-key or --passphrase"
        raise ValidationError(message)
    if sum((new_key is not None, generate is not None, passphrase)) > 1:
        message = f"use only one of {_NEW_KEY_OPTION}, --generate-key, --passphrase"
        raise ValidationError(message)
    # new_secret refuses these too, but only after rekey has asked for the old secret. The same
    # wording as there; the existence check is repeated (atomically) when the file is written.
    if new_key is not None:
        parse_key_path(new_key, option=_NEW_KEY_OPTION)
    if generate == _STDOUT_PATH:
        message = (
            "--generate-key needs a file path; to print a new key use 'envs keygen -' and "
            f"pass it with '{_NEW_KEY_OPTION} -'"
        )
        raise ValidationError(message)
    if generate == _NO_FILE_PATH:
        message = "--generate-key needs a file path"
        raise ValidationError(message)
    if generate is not None and (generate.exists() or generate.is_symlink()):
        message = f"key file '{generate}' already exists; refusing to overwrite it"
        raise ValidationError(message)


def _new(
    ctx: typer.Context, *, new_key: str | None, generate: Path | None, passphrase: bool
) -> NewSecret:
    new = new_secret(
        ctx, key=new_key, generate=generate, passphrase=passphrase, key_option=_NEW_KEY_OPTION
    )
    # Never None: _require_one has made sure exactly one option was given.
    return cast("NewSecret", new)


def _mode(new: NewSecret) -> str:
    return "keyfile" if isinstance(new.secret, KeyMaterial) else "passphrase"
