"""`envs ls-store`: every store with its encryption, never its contents (spec §6.2, D1, PD 23).

An empty backend names its location on stderr, so a mistyped connection is visible (D42).
"""

from datetime import UTC, datetime
from typing import Final

import typer

from environment_store.cli.options import JsonOpt
from environment_store.cli.output import JsonValue, emit_json, err, out, table
from environment_store.cli.state import get_state
from environment_store.core.connection import connection_location
from environment_store.core.models import StoreInfo

__all__ = ["encryption_label", "ls_store"]

_HEADER: Final = ("name", "encryption")
_UTC_SUFFIX: Final = "+00:00"


def ls_store(ctx: typer.Context, *, as_json: JsonOpt = False) -> None:
    """List all stores and whether they are encrypted; needs no key."""
    state = get_state(ctx)
    infos = state.open_store(ctx).list_stores()
    if not infos:
        # D42: a mistyped connection must not look like an empty backend.
        err(f"no stores in {connection_location(state.settings().require_connection())}")
    if as_json:
        emit_json([_json_entry(info) for info in infos])
        return
    if infos:
        out(table([_HEADER, *((info.name, encryption_label(info)) for info in infos)]))


def encryption_label(info: StoreInfo) -> str:
    """Describe a store's encryption for the human listing.

    Args:
        info: The listing entry.

    Returns:
        `plain`, `encrypted (<mode>)`, or `encrypted (unknown)` for cipher metadata this
        version does not recognise. No variable count: it would leak information (D1).
    """
    if not info.encrypted:
        return "plain"
    mode = "unknown" if info.key_mode is None else info.key_mode.value
    return f"encrypted ({mode})"


def _json_entry(info: StoreInfo) -> dict[str, JsonValue]:
    return {
        "name": info.name,
        "encrypted": info.encrypted,
        "key_mode": None if info.key_mode is None else info.key_mode.value,
        "revision": info.revision,
        "created_at": _timestamp(info.created_at),
        "updated_at": _timestamp(info.updated_at),
    }


def _timestamp(moment: datetime) -> str:
    # ISO 8601 in UTC with the conventional "Z" suffix (PD 23).
    text = moment.astimezone(UTC).isoformat()
    return text.removesuffix(_UTC_SUFFIX) + "Z"
