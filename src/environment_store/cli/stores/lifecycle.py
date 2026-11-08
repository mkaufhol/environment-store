"""`envs create-store` and `envs rm-store` (spec §6.3, §6.4, D21, PD 24, PD 33)."""

from typing import Annotated

import typer

from environment_store.cli.completion.candidates import complete_stores
from environment_store.cli.confirm import require_confirmation
from environment_store.cli.options import CreateKeyOpt, GenerateKeyOpt, PassphraseOpt, YesOpt
from environment_store.cli.output import err
from environment_store.cli.secrets import keep_or_discard, new_secret
from environment_store.cli.state import get_state
from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_store_name

__all__ = ["ExistingNameArg", "NameArg", "create_store", "rm_store"]

NameArg = Annotated[str, typer.Argument(metavar="NAME", help="The store name.", show_default=False)]
"""A new store's name: never completed (D54)."""
ExistingNameArg = Annotated[
    str,
    typer.Argument(
        metavar="NAME",
        help="The store name.",
        show_default=False,
        autocompletion=complete_stores,
    ),
]
"""An existing store's name: completes the stores of the backend (D54)."""
EncryptOpt = Annotated[
    bool,
    typer.Option(
        "-e",
        "--encrypt",
        help="Create an encrypted store; needs exactly one of -k, --generate-key, --passphrase.",
    ),
]


def create_store(  # noqa: PLR0913 - one parameter per documented option (spec §6.3)
    ctx: typer.Context,
    name: NameArg,
    *,
    encrypt: EncryptOpt = False,
    key: CreateKeyOpt = None,
    generate: GenerateKeyOpt = None,
    passphrase: PassphraseOpt = False,
) -> None:
    """Create a new, empty store, optionally encrypted."""
    # Everything that can be refused is checked before a key file is generated.
    validate_store_name(name)
    if not encrypt and (key is not None or generate is not None or passphrase):
        message = "-k, --generate-key and --passphrase encrypt the new store: add -e/--encrypt"
        raise ValidationError(message)
    store = get_state(ctx).open_store(ctx)
    chosen = new_secret(ctx, key=key, generate=generate, passphrase=passphrase, key_option="-k")
    if encrypt and chosen is None:
        message = "an encrypted store needs one of -k <path>, --generate-key <path>, --passphrase"
        raise ValidationError(message)
    secret = None if chosen is None else chosen.secret
    with keep_or_discard(chosen, target=name, store=store, creates_target=True):
        store.create_store(name, encrypt=encrypt, key=secret)
    err(f"created store {name!r}")


def rm_store(ctx: typer.Context, name: ExistingNameArg, *, yes: YesOpt = False) -> None:
    """Delete a store; needs no key, also when it is encrypted."""
    store = get_state(ctx).open_store(ctx)
    # A missing store fails with 2 before anyone is asked (D21: no key, only the name).
    store.store_info(name)
    require_confirmation(ctx, f"Delete store {name!r}?", yes=yes)
    store.delete_store(name)
    err(f"deleted store {name!r}")
