"""Hypothesis strategies for the domain model.

Shared by the core tests, the adapter contract suite and the adapter tests, so that every layer
is exercised with the same tricky names, values and records.
"""

from datetime import UTC, datetime
from typing import Final

from hypothesis import strategies as st

from environment_store.core.models import Cipher, CipherMeta, KdfParams, KeyMode, StoreRecord
from environment_store.core.validation import STORE_NAME_PATTERN, VARIABLE_NAME_PATTERN

__all__ = [
    "MAX_REVISION",
    "cipher_metas",
    "invalid_store_names",
    "invalid_variable_names",
    "kdf_params",
    "plain_records",
    "sealed_records",
    "store_names",
    "timestamps",
    "values",
    "variable_maps",
    "variable_names",
]

MAX_REVISION: Final[int] = 2**31 - 1
"""Largest revision every backend can hold (PostgreSQL `INTEGER`)."""

_DANGEROUS_STORE_NAMES: Final[tuple[str, ...]] = (
    "",
    "../x",
    "..",
    ".",
    "a/b",
    "a\\b",
    "/abs",
    "A",
    "Base",
    "-a",
    "_a",
    "a.b",
    "a b",
    "a\n",
    "x" * 64,
    "a\x00",
    "café",
)
_TRICKY_VALUES: Final[tuple[str, ...]] = (
    "",
    " ",
    "line1\nline2",
    "line1\r\nline2\n",
    "-----BEGIN KEY-----\nabc==\n-----END KEY-----\n",
    "  padded  ",
    "\ttab",
    '"double"',
    "'single'",
    "it's",
    "$HOME ${HOME} $(id)",
    "a=b=c",
    "#not a comment",
    "back\\slash\\n",
    "unicode äöü ✓ 😀",
)
_TIMESTAMP_MIN: Final[datetime] = datetime(1970, 1, 1)  # noqa: DTZ001 - st.datetimes needs naive
_TIMESTAMP_MAX: Final[datetime] = datetime(2999, 12, 31, 23, 59, 59, 999999)  # noqa: DTZ001


def store_names() -> st.SearchStrategy[str]:
    """Valid store names (D27)."""
    return st.from_regex(STORE_NAME_PATTERN, fullmatch=True)


def invalid_store_names() -> st.SearchStrategy[str]:
    """Strings that violate D27, including path traversal and uppercase names."""
    return st.one_of(
        st.sampled_from(_DANGEROUS_STORE_NAMES),
        st.text(max_size=70).filter(lambda name: STORE_NAME_PATTERN.fullmatch(name) is None),
    )


def variable_names() -> st.SearchStrategy[str]:
    """Valid, portable POSIX variable names (D33)."""
    return st.from_regex(VARIABLE_NAME_PATTERN, fullmatch=True)


def invalid_variable_names() -> st.SearchStrategy[str]:
    """Strings that are not portable variable names."""
    return st.one_of(
        st.sampled_from(["", "1A", "A-B", "A.B", "A B", "A=B", "Ä", "A\n"]),
        st.text(max_size=20).filter(lambda name: VARIABLE_NAME_PATTERN.fullmatch(name) is None),
    )


def values() -> st.SearchStrategy[str]:
    """Valid values (D28): empty, multi-line, unicode, quotes, `$`, `=`, surrounding whitespace.

    Never NUL and never lone surrogates.
    """
    text = st.text(st.characters(codec="utf-8", exclude_characters="\x00"))
    pieces = st.one_of(st.sampled_from(_TRICKY_VALUES), text)
    return st.one_of(pieces, st.lists(pieces, max_size=4).map("".join))


def variable_maps(*, max_size: int = 8) -> st.SearchStrategy[dict[str, str]]:
    """Valid variable mappings, possibly empty."""
    return st.dictionaries(variable_names(), values(), max_size=max_size)


def timestamps() -> st.SearchStrategy[datetime]:
    """Aware UTC datetimes with microseconds, within the range every backend stores."""
    return st.datetimes(min_value=_TIMESTAMP_MIN, max_value=_TIMESTAMP_MAX, timezones=st.just(UTC))


@st.composite
def kdf_params(draw: st.DrawFn) -> KdfParams:
    """Valid Argon2id parameters within the D34 bounds.

    They may be expensive: use them as metadata, not to derive keys.
    """
    lanes = draw(st.integers(min_value=1, max_value=16))
    return KdfParams(
        iterations=draw(st.integers(min_value=1, max_value=10)),
        memory_kib=draw(st.integers(min_value=8 * lanes, max_value=1048576)),
        lanes=lanes,
        salt=draw(st.binary(min_size=16, max_size=16)),
    )


def cipher_metas() -> st.SearchStrategy[CipherMeta]:
    """Cipher metadata for both key modes."""
    return st.one_of(
        st.just(CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE)),
        kdf_params().map(
            lambda kdf: CipherMeta(cipher=Cipher.AES256GCM, mode=KeyMode.PASSPHRASE, kdf=kdf)
        ),
    )


def _revisions(revisions: st.SearchStrategy[int] | None) -> st.SearchStrategy[int]:
    if revisions is None:
        return st.integers(min_value=1, max_value=MAX_REVISION)
    return revisions


@st.composite
def plain_records(
    draw: st.DrawFn, *, revisions: st.SearchStrategy[int] | None = None
) -> StoreRecord:
    """Valid plaintext records; `revisions` overrides the revision strategy (e.g. `just(1)`)."""
    created_at, updated_at = sorted([draw(timestamps()), draw(timestamps())])
    return StoreRecord.plain(
        name=draw(store_names()),
        variables=draw(variable_maps()),
        revision=draw(_revisions(revisions)),
        created_at=created_at,
        updated_at=updated_at,
    )


@st.composite
def sealed_records(
    draw: st.DrawFn, *, revisions: st.SearchStrategy[int] | None = None
) -> StoreRecord:
    """Valid encrypted records with arbitrary binary ciphertexts (adapters treat them opaquely)."""
    created_at, updated_at = sorted([draw(timestamps()), draw(timestamps())])
    return StoreRecord.sealed(
        name=draw(store_names()),
        ciphertext=draw(st.binary(max_size=256)),
        cipher_meta=draw(cipher_metas()),
        revision=draw(_revisions(revisions)),
        created_at=created_at,
        updated_at=updated_at,
    )
