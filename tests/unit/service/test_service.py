from collections.abc import Callable, Collection
from datetime import timedelta

import pytest
from hypothesis import given, settings

from environment_store.core.errors import (
    ConcurrentModificationError,
    DecryptionError,
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    NotEncryptedError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
    VariableExistsError,
    VariableNotFoundError,
)
from environment_store.core.models import Cipher, CipherMeta, KeyMode, Source, StoreInfo
from environment_store.core.secrets import KeyMaterial, Passphrase, Secret
from environment_store.crypto.keyfile import format_key
from environment_store.service import StoreService
from tests.support.clock import DEFAULT_START, FakeClock
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend
from tests.support.strategies import variable_maps
from tests.unit.service.conftest import (
    KEY,
    OTHER_KEY,
    OTHER_PASSPHRASE,
    PASSPHRASE,
    CheapKdf,
    RacingAdapter,
    bump,
)

type MakeService = Callable[[MemoryAdapter], StoreService]


# --- create, list, delete ----------------------------------------------------------------------


def test_create_plain_store_returns_its_info(service: StoreService) -> None:
    info = service.create_store("base")

    assert info == StoreInfo(
        name="base",
        encrypted=False,
        key_mode=None,
        revision=1,
        created_at=DEFAULT_START,
        updated_at=DEFAULT_START,
    )
    assert service.read_variables("base") == {}


def test_create_keyfile_store_seals_an_empty_payload(
    service: StoreService, backend: MemoryBackend
) -> None:
    info = service.create_store("vault", secret=KEY)

    assert (info.encrypted, info.key_mode, info.revision) == (True, KeyMode.KEYFILE, 1)
    assert backend.read("vault").cipher_meta == CipherMeta(
        cipher=Cipher.AES256GCM, mode=KeyMode.KEYFILE
    )
    assert service.read_variables("vault", secret=KEY) == {}


def test_create_passphrase_store_stores_new_kdf_parameters(
    service: StoreService, backend: MemoryBackend, kdf: CheapKdf
) -> None:
    info = service.create_store("vault", secret=PASSPHRASE)

    meta = backend.read("vault").cipher_meta
    assert info.key_mode is KeyMode.PASSPHRASE
    assert meta is not None
    assert meta.kdf is not None
    assert meta.kdf.salt == (1).to_bytes(16, "big")
    assert kdf.calls == 1
    assert service.read_variables("vault", secret=PASSPHRASE) == {}


def test_create_existing_store_raises_store_exists(service: StoreService) -> None:
    service.create_store("base")

    with pytest.raises(StoreExistsError):
        service.create_store("base", secret=KEY)


def test_list_stores_lists_every_store_sorted_with_its_key_mode(service: StoreService) -> None:
    service.create_store("zeta")
    service.create_store("alpha", secret=KEY)
    service.create_store("mid", secret=PASSPHRASE)

    listing = service.list_stores()

    assert [(info.name, info.key_mode) for info in listing] == [
        ("alpha", KeyMode.KEYFILE),
        ("mid", KeyMode.PASSPHRASE),
        ("zeta", None),
    ]


def test_delete_store_needs_no_key_for_an_encrypted_store(service: StoreService) -> None:
    # A store whose key is lost must still be removable.
    service.create_store("vault", secret=KEY)

    service.delete_store("vault")

    assert service.list_stores() == []


def test_delete_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.delete_store("missing")


# --- parse_secret ------------------------------------------------------------------------------


def test_parse_secret_for_a_keyfile_store_parses_the_key_file(service: StoreService) -> None:
    service.create_store("vault", secret=KEY)

    assert service.parse_secret("vault", format_key(KEY)) == KEY


def test_parse_secret_for_a_keyfile_store_rejects_a_passphrase(service: StoreService) -> None:
    service.create_store("vault", secret=KEY)

    with pytest.raises(InvalidKeyFileError):
        service.parse_secret("vault", "correct horse\n")


def test_parse_secret_for_a_passphrase_store_strips_one_trailing_newline(
    service: StoreService,
) -> None:
    service.create_store("vault", secret=PASSPHRASE)

    assert service.parse_secret("vault", "pass word \n\n") == Passphrase(text="pass word \n")


def test_parse_secret_for_a_passphrase_store_refuses_a_key_file(service: StoreService) -> None:
    service.create_store("vault", secret=PASSPHRASE)

    with pytest.raises(KeyModeMismatchError, match="key file"):
        service.parse_secret("vault", format_key(KEY))


def test_parse_secret_for_a_plaintext_store_raises_not_encrypted(service: StoreService) -> None:
    service.create_store("base")

    with pytest.raises(NotEncryptedError):
        service.parse_secret("base", format_key(KEY))


def test_parse_secret_for_a_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.parse_secret("missing", "text")


# --- read --------------------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, KEY, PASSPHRASE])
def test_read_variables_returns_what_was_set(service: StoreService, secret: Secret | None) -> None:
    service.create_store("store", secret=secret)
    service.set_variables("store", {"A": "1", "B": "two\nlines"}, secret=secret)

    assert service.read_variables("store", secret=secret) == {"A": "1", "B": "two\nlines"}


def test_read_variables_returns_a_mutable_copy(service: StoreService) -> None:
    service.create_store("base")
    service.set_variables("base", {"A": "1"})

    variables = service.read_variables("base")
    variables["B"] = "2"

    assert service.read_variables("base") == {"A": "1"}


def test_read_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.read_variables("missing")


_CONTENT_OPERATIONS: dict[str, Callable[[StoreService, Secret | None], object]] = {
    "read": lambda service, secret: service.read_variables("store", secret=secret),
    "set": lambda service, secret: service.set_variables("store", {"B": "2"}, secret=secret),
    "delete": lambda service, secret: service.delete_variables("store", ["A"], secret=secret),
    "load": lambda service, secret: service.load([Source(name="store", secret=secret)]),
}


@pytest.mark.parametrize(
    "case",
    [
        (KEY, None, KeyRequiredError),
        (PASSPHRASE, None, KeyRequiredError),
        (None, KEY, NotEncryptedError),
        (None, PASSPHRASE, NotEncryptedError),
        (KEY, PASSPHRASE, KeyModeMismatchError),
        (PASSPHRASE, KEY, KeyModeMismatchError),
        (KEY, OTHER_KEY, DecryptionError),
        (PASSPHRASE, OTHER_PASSPHRASE, DecryptionError),
    ],
)
@pytest.mark.parametrize("operation", list(_CONTENT_OPERATIONS))
def test_secret_must_match_the_store_in_every_content_operation(
    service: StoreService,
    backend: MemoryBackend,
    case: tuple[Secret | None, Secret | None, type[Exception]],
    operation: str,
) -> None:
    created_with, supplied, error = case
    service.create_store("store", secret=created_with)
    service.set_variables("store", {"A": "1"}, secret=created_with)
    before = backend.read("store")

    with pytest.raises(error):
        _CONTENT_OPERATIONS[operation](service, supplied)

    assert backend.read("store") == before


def test_error_messages_never_contain_secrets(service: StoreService) -> None:
    service.create_store("vault", secret=PASSPHRASE)
    service.set_variables("vault", {"API_TOKEN": "tok-123"}, secret=PASSPHRASE)

    with pytest.raises(DecryptionError) as excinfo:
        service.read_variables("vault", secret=OTHER_PASSPHRASE)

    message = str(excinfo.value)
    for secret in ("API_TOKEN", "tok-123", PASSPHRASE.text, OTHER_PASSPHRASE.text):
        assert secret not in message


# --- set ---------------------------------------------------------------------------------------


def test_set_variables_writes_one_revision_with_the_clock_time(
    service: StoreService, backend: MemoryBackend, clock: FakeClock
) -> None:
    service.create_store("base")
    expected_time = clock.now

    service.set_variables("base", {"A": "1", "B": "2"})

    record = backend.read("base")
    assert record.revision == 2
    assert record.updated_at == expected_time
    assert record.created_at == DEFAULT_START
    assert dict(record.variables or {}) == {"A": "1", "B": "2"}


def test_set_variables_without_overwrite_refuses_all_conflicts_and_writes_nothing(
    service: StoreService, backend: MemoryBackend
) -> None:
    service.create_store("base")
    service.set_variables("base", {"A": "1", "C": "3"})
    before = backend.read("base")

    with pytest.raises(VariableExistsError) as excinfo:
        service.set_variables("base", {"C": "x", "B": "2", "A": "y"})

    assert excinfo.value.names == ("C", "A")
    assert excinfo.value.store == "base"
    assert backend.read("base") == before


@pytest.mark.parametrize("secret", [None, KEY])
def test_set_variables_with_overwrite_replaces_existing_values(
    service: StoreService, secret: Secret | None
) -> None:
    service.create_store("store", secret=secret)
    service.set_variables("store", {"A": "1", "B": "2"}, secret=secret)

    service.set_variables("store", {"A": "new", "C": "3"}, secret=secret, overwrite=True)

    assert service.read_variables("store", secret=secret) == {"A": "new", "B": "2", "C": "3"}


def test_set_variables_on_an_encrypted_store_keeps_no_plaintext_in_the_record(
    service: StoreService, backend: MemoryBackend
) -> None:
    service.create_store("vault", secret=KEY)

    service.set_variables("vault", {"DB_PASSWORD": "hunter2"}, secret=KEY)

    record = backend.read("vault")
    assert record.variables is None
    assert record.ciphertext is not None
    assert b"hunter2" not in record.ciphertext
    assert b"DB_PASSWORD" not in record.ciphertext


def test_every_write_reencrypts_with_a_fresh_nonce_and_keeps_the_metadata(
    service: StoreService, backend: MemoryBackend
) -> None:
    # The salt stays the same until rekey.
    service.create_store("vault", secret=PASSPHRASE)
    first = backend.read("vault")

    service.set_variables("vault", {"A": "1"}, secret=PASSPHRASE)
    service.set_variables("vault", {"A": "1"}, secret=PASSPHRASE, overwrite=True)

    second = backend.read("vault")
    assert second.cipher_meta == first.cipher_meta
    assert first.ciphertext is not None
    assert second.ciphertext is not None
    assert second.ciphertext[:12] != first.ciphertext[:12]


@pytest.mark.parametrize(
    "values",
    [{}, {"not valid": "x"}, {"A": "nul\x00"}],
    ids=["empty", "bad-name", "nul-value"],
)
def test_set_variables_rejects_invalid_input_before_touching_the_store(
    service: StoreService, backend: MemoryBackend, values: dict[str, str]
) -> None:
    service.create_store("base")
    before = backend.read("base")

    with pytest.raises(ValidationError):
        service.set_variables("base", values)

    assert backend.read("base") == before


def test_set_variables_on_a_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.set_variables("missing", {"A": "1"})


def test_set_variables_after_a_concurrent_write_raises_and_loses_nothing(
    backend: MemoryBackend, make_service: MakeService
) -> None:
    make_service(backend.open()).create_store("base")
    service = make_service(RacingAdapter(backend, bump("base")))

    with pytest.raises(ConcurrentModificationError):
        service.set_variables("base", {"A": "1"})

    assert backend.read("base").revision == 2
    assert dict(backend.read("base").variables or {}) == {}


def test_write_never_sets_updated_at_before_created_at(
    backend: MemoryBackend, kdf: CheapKdf
) -> None:
    # Another machine with a clock ahead created the store: keep the record valid.
    ahead = StoreService(backend.open(), clock=FakeClock(DEFAULT_START + timedelta(hours=1)))
    ahead.create_store("base")
    behind = StoreService(backend.open(), clock=FakeClock(), kdf_params_factory=kdf)

    behind.set_variables("base", {"A": "1"})

    record = backend.read("base")
    assert record.updated_at == record.created_at == DEFAULT_START + timedelta(hours=1)


@settings(max_examples=25)
@given(variables=variable_maps(max_size=5))
def test_any_variables_round_trip_through_an_encrypted_store(variables: dict[str, str]) -> None:
    service = StoreService(MemoryAdapter(), clock=FakeClock(), kdf_params_factory=CheapKdf())
    service.create_store("vault", secret=KEY)

    if variables:
        service.set_variables("vault", variables, secret=KEY)

    assert service.read_variables("vault", secret=KEY) == variables


# --- delete variables --------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, KEY, PASSPHRASE])
def test_delete_variables_removes_them_in_one_write(
    service: StoreService, backend: MemoryBackend, secret: Secret | None
) -> None:
    service.create_store("store", secret=secret)
    service.set_variables("store", {"A": "1", "B": "2", "C": "3"}, secret=secret)

    service.delete_variables("store", ["A", "C", "A"], secret=secret)

    assert service.read_variables("store", secret=secret) == {"B": "2"}
    assert backend.read("store").revision == 3


def test_delete_missing_variables_lists_all_of_them_and_writes_nothing(
    service: StoreService, backend: MemoryBackend
) -> None:
    service.create_store("base")
    service.set_variables("base", {"A": "1"})
    before = backend.read("base")

    with pytest.raises(VariableNotFoundError) as excinfo:
        service.delete_variables("base", ["Z", "A", "Y", "Z"])

    assert excinfo.value.names == ("Z", "Y")
    assert excinfo.value.store == "base"
    assert backend.read("base") == before


@pytest.mark.parametrize("names", [[], ["not valid"], "A"], ids=["empty", "bad-name", "string"])
def test_delete_variables_rejects_invalid_names(
    service: StoreService, backend: MemoryBackend, names: Collection[str]
) -> None:
    service.create_store("base")
    service.set_variables("base", {"A": "1"})
    before = backend.read("base")

    with pytest.raises(ValidationError):
        service.delete_variables("base", names)

    assert backend.read("base") == before


# --- load --------------------------------------------------------------------------------------


def test_load_returns_every_source_in_order_with_its_own_secret(service: StoreService) -> None:
    service.create_store("base")
    service.set_variables("base", {"A": "base"})
    service.create_store("keyed", secret=KEY)
    service.set_variables("keyed", {"A": "keyed"}, secret=KEY)
    service.create_store("phrase", secret=PASSPHRASE)
    service.set_variables("phrase", {"B": "phrase"}, secret=PASSPHRASE)

    loaded = service.load(
        [
            Source(name="phrase", secret=PASSPHRASE),
            Source(name="base"),
            Source(name="keyed", secret=KEY),
            Source(name="base"),
        ]
    )

    assert loaded == [
        ("phrase", {"B": "phrase"}),
        ("base", {"A": "base"}),
        ("keyed", {"A": "keyed"}),
        ("base", {"A": "base"}),
    ]


def test_load_of_nothing_returns_nothing(service: StoreService) -> None:
    assert service.load([]) == []


def test_load_with_a_missing_store_raises_store_not_found(service: StoreService) -> None:
    service.create_store("base")

    with pytest.raises(StoreNotFoundError):
        service.load([Source(name="base"), Source(name="missing")])


# --- dependencies ------------------------------------------------------------------------------


def test_service_defaults_to_the_real_clock(backend: MemoryBackend) -> None:
    service = StoreService(backend.open())

    info = service.create_store("base")

    assert info.created_at.utcoffset() == timedelta(0)
    assert service.read_variables("base") == {}


def test_service_defaults_to_the_rfc_9106_kdf_parameters(backend: MemoryBackend) -> None:
    # One real Argon2id run (t=3, m=64 MiB, p=4): the default must not be weakened.
    StoreService(backend.open()).create_store("vault", secret=PASSPHRASE)

    meta = backend.read("vault").cipher_meta
    assert meta is not None
    assert meta.kdf is not None
    assert (meta.kdf.name, meta.kdf.iterations, meta.kdf.memory_kib, meta.kdf.lanes) == (
        "argon2id",
        3,
        65536,
        4,
    )
    assert len(meta.kdf.salt) == 16


def test_parse_secret_rejects_a_passphrase_with_a_lone_surrogate(service: StoreService) -> None:
    # Undecodable stdin bytes become lone surrogates; refused before Argon2id sees them.
    service.create_store("vault", secret=PASSPHRASE)

    with pytest.raises(ValidationError, match="not valid UTF-8") as excinfo:
        service.parse_secret("vault", "hunter2\udc80secret\n")

    assert "hunter2" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_service_exposes_its_adapter(backend: MemoryBackend) -> None:
    adapter = backend.open()

    assert StoreService(adapter).adapter is adapter


@pytest.mark.parametrize("secret", [KEY, PASSPHRASE])
def test_secret_reprs_stay_redacted_in_service_errors(
    service: StoreService, secret: KeyMaterial | Passphrase
) -> None:
    service.create_store("base")

    with pytest.raises(NotEncryptedError) as excinfo:
        service.read_variables("base", secret=secret)

    assert "redacted" not in str(excinfo.value)
    assert str(excinfo.value).startswith("store 'base' is not encrypted")
