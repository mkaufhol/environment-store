from typing import Final

import pytest

from environment_store.core.models import KdfParams
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.crypto import kdf
from environment_store.crypto.kdf import derive_key, new_kdf_params

# Cheap parameters: Argon2id is slow by design, so only the defaults test uses the real ones.
_SALT: Final[bytes] = bytes(range(16))
_CHEAP: Final[KdfParams] = KdfParams(iterations=1, memory_kib=8, lanes=1, salt=_SALT)
# Argon2id v1.3, t=1, m=8 KiB, p=1, salt 00..0f, 32 bytes, password "password"
# PHC: $argon2id$v=19$m=8,t=1,p=1$AAECAwQFBgcICQoLDA0ODw
#      $OgCJY8Zff/pzMakLq9H9F+qfA70FNWuFfOtD97cICtw
_KNOWN_VECTOR: Final[str] = "3a008963c65f7ffa7331a90babd1fd17ea9f03bd05356b857ceb43f7b7080adc"


def test_new_kdf_params_use_the_spec_defaults_with_a_random_16_byte_salt() -> None:
    first, second = new_kdf_params(), new_kdf_params()

    # RFC 9106 second recommended option (D34): t=3, m=64 MiB, p=4.
    assert (first.name, first.iterations, first.memory_kib, first.lanes) == (
        "argon2id",
        3,
        65536,
        4,
    )
    assert len(first.salt) == 16
    assert first.salt != second.salt


def test_new_kdf_params_take_the_salt_from_the_secrets_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_token_bytes(length: int) -> bytes:
        calls.append(length)
        return b"\x07" * length

    monkeypatch.setattr(kdf.secrets, "token_bytes", fake_token_bytes)

    assert new_kdf_params().salt == b"\x07" * 16
    assert calls == [16]


def test_derive_key_matches_a_known_argon2id_vector() -> None:
    key = derive_key(Passphrase(text="password"), _CHEAP)

    assert key.key.hex() == _KNOWN_VECTOR


def test_derive_key_returns_key_material_and_is_deterministic() -> None:
    first = derive_key(Passphrase(text="correct horse"), _CHEAP)

    assert isinstance(first, KeyMaterial)
    assert derive_key(Passphrase(text="correct horse"), _CHEAP) == first


def test_derive_key_depends_on_the_passphrase() -> None:
    assert derive_key(Passphrase(text="a"), _CHEAP) != derive_key(Passphrase(text="b"), _CHEAP)


# Each case changes exactly one parameter against its baseline. Argon2id needs at least 8 KiB
# per lane, so the lanes case starts from 16 KiB.
@pytest.mark.parametrize(
    ("base", "other"),
    [
        (_CHEAP, KdfParams(iterations=1, memory_kib=8, lanes=1, salt=b"\xff" * 16)),
        (_CHEAP, KdfParams(iterations=2, memory_kib=8, lanes=1, salt=_SALT)),
        (_CHEAP, KdfParams(iterations=1, memory_kib=16, lanes=1, salt=_SALT)),
        (
            KdfParams(iterations=1, memory_kib=16, lanes=1, salt=_SALT),
            KdfParams(iterations=1, memory_kib=16, lanes=2, salt=_SALT),
        ),
    ],
    ids=["salt", "iterations", "memory", "lanes"],
)
def test_derive_key_depends_on_every_parameter(base: KdfParams, other: KdfParams) -> None:
    passphrase = Passphrase(text="correct horse")

    assert derive_key(passphrase, other) != derive_key(passphrase, base)


def test_derive_key_accepts_non_ascii_passphrases() -> None:
    passphrase = Passphrase(text="pässwört ✓")

    assert derive_key(passphrase, _CHEAP) != derive_key(Passphrase(text="p?ssw?rt ?"), _CHEAP)
