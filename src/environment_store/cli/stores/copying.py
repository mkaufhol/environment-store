"""`envs cp-store` and `envs mv-store` (spec §6.5, D4, D5, D15, D33, PD 5, PD 33).

The target is encrypted like the source by default (re-encrypted, because a ciphertext is bound
to its store name, D5), as plaintext with `--plain` (the documented way to decrypt, D4), or with
a new secret. `mv-store` is a copy followed by deleting the source; the library makes sure a
failure never leaves zero copies.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Literal

import typer

from environment_store.cli.options import GenerateKeyOpt, NewKeyOpt, PassphraseOpt, WriteKeyOpt
from environment_store.cli.output import err
from environment_store.cli.secrets import existing_secret, keep_or_discard, new_secret
from environment_store.cli.state import get_state
from environment_store.core.errors import ValidationError
from environment_store.core.validation import validate_store_name

if TYPE_CHECKING:
    from environment_store.library.sources import KeyInput

__all__ = ["cp_store", "mv_store"]

_NEW_KEY_OPTION: Final = "--new-key"

SrcArg = Annotated[str, typer.Argument(metavar="SRC", help="The source store.", show_default=False)]
DstArg = Annotated[str, typer.Argument(metavar="DST", help="The new store.", show_default=False)]
ToOpt = Annotated[
    str | None,
    typer.Option(
        "--to",
        metavar="URL",
        help="Connection string of another backend; there DST may equal SRC.",
        show_default=False,
    ),
]
PlainOpt = Annotated[
    bool,
    typer.Option("--plain", help="Make an unencrypted copy (the way to decrypt a store)."),
]


def cp_store(  # noqa: PLR0913 - one parameter per documented option (spec §6.5)
    ctx: typer.Context,
    src: SrcArg,
    dst: DstArg,
    *,
    to: ToOpt = None,
    key: WriteKeyOpt = None,
    plain: PlainOpt = False,
    new_key: NewKeyOpt = None,
    generate: GenerateKeyOpt = None,
    passphrase: PassphraseOpt = False,
) -> None:
    """Copy a store under a new name, optionally into another backend."""
    _transfer(
        ctx,
        src,
        dst,
        _Options(
            to=to,
            key=key,
            plain=plain,
            new_key=new_key,
            generate=generate,
            passphrase=passphrase,
        ),
        move=False,
    )
    err(f"copied store {src!r} to {dst!r}")


def mv_store(  # noqa: PLR0913 - one parameter per documented option (spec §6.5)
    ctx: typer.Context,
    src: SrcArg,
    dst: DstArg,
    *,
    to: ToOpt = None,
    key: WriteKeyOpt = None,
    plain: PlainOpt = False,
    new_key: NewKeyOpt = None,
    generate: GenerateKeyOpt = None,
    passphrase: PassphraseOpt = False,
) -> None:
    """Rename a store, or move it into another backend."""
    _transfer(
        ctx,
        src,
        dst,
        _Options(
            to=to,
            key=key,
            plain=plain,
            new_key=new_key,
            generate=generate,
            passphrase=passphrase,
        ),
        move=True,
    )
    err(f"moved store {src!r} to {dst!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class _Options:
    """The options cp-store and mv-store share."""

    to: str | None
    key: str | None
    plain: bool
    new_key: str | None
    generate: Path | None
    passphrase: bool


def _transfer(ctx: typer.Context, src: str, dst: str, options: _Options, *, move: bool) -> None:
    # Everything that can be refused without I/O is checked before a key is read or generated.
    validate_store_name(src)
    validate_store_name(dst)
    if options.to is None and dst == src:
        message = (
            f"store {src!r} cannot be copied onto itself: choose another name, or another "
            "backend with --to"
        )
        raise ValidationError(message)
    if options.plain and (
        options.new_key is not None or options.generate is not None or options.passphrase
    ):
        message = f"use only one of --plain, {_NEW_KEY_OPTION}, --generate-key, --passphrase"
        raise ValidationError(message)
    state = get_state(ctx)
    source = state.open_store(ctx)
    # Opened before any prompt, so a wrong --to never costs one.
    target = source if options.to is None else state.open_store(ctx, connection=options.to)
    secret = existing_secret(ctx, src, options.key)
    chosen = new_secret(
        ctx,
        key=options.new_key,
        generate=options.generate,
        passphrase=options.passphrase,
        key_option=_NEW_KEY_OPTION,
    )
    encryption: Literal["same", "plain"] | KeyInput = "plain" if options.plain else "same"
    if chosen is not None:
        encryption = chosen.secret
    destination = None if options.to is None else target
    with keep_or_discard(chosen, target=dst, store=target, creates_target=True):
        if move:
            source.move_store(src, dst, key=secret, encryption=encryption, to=destination)
        else:
            source.copy_store(src, dst, key=secret, encryption=encryption, to=destination)
