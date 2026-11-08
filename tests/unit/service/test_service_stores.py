from collections.abc import Callable
from typing import Final, Literal, cast

import pytest

from environment_store.core.errors import (
    AlreadyEncryptedError,
    BackendError,
    ConcurrentModificationError,
    DecryptionError,
    KeyModeMismatchError,
    KeyRequiredError,
    NotEncryptedError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
)
from environment_store.core.models import KeyMode, Source
from environment_store.core.secrets import Secret
from environment_store.service import StoreService
from tests.support.clock import DEFAULT_START
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend
from tests.unit.service.conftest import (
    KEY,
    OTHER_KEY,
    OTHER_PASSPHRASE,
    PASSPHRASE,
    CheapKdf,
    FailingDeleteAdapter,
    RacingAdapter,
    UntouchableAdapter,
    bump,
)

type MakeService = Callable[[MemoryAdapter], StoreService]
type Encryption = Literal["same", "plain"] | Secret

_VARIABLES: Final[dict[str, str]] = {"A": "1", "B": "multi\nline"}


def _filled(service: StoreService, name: str, secret: Secret | None) -> None:
    service.create_store(name, secret=secret)
    service.set_variables(name, _VARIABLES, secret=secret)


# --- encrypt -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("secret", "mode"), [(KEY, KeyMode.KEYFILE), (PASSPHRASE, KeyMode.PASSPHRASE)]
)
def test_encrypt_store_turns_a_plaintext_store_into_an_encrypted_one(
    service: StoreService, backend: MemoryBackend, secret: Secret, mode: KeyMode
) -> None:
    _filled(service, "base", None)

    service.encrypt_store("base", secret=secret)

    record = backend.read("base")
    assert (record.encrypted, record.info.key_mode, record.revision) == (True, mode, 3)
    assert service.read_variables("base", secret=secret) == _VARIABLES


def test_encrypt_an_encrypted_store_raises_already_encrypted(service: StoreService) -> None:
    service.create_store("vault", secret=KEY)

    with pytest.raises(AlreadyEncryptedError):
        service.encrypt_store("vault", secret=OTHER_KEY)


def test_encrypt_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.encrypt_store("missing", secret=KEY)


# --- rekey -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        (KEY, OTHER_KEY, KeyMode.KEYFILE, DecryptionError),
        (KEY, PASSPHRASE, KeyMode.PASSPHRASE, KeyModeMismatchError),
        (PASSPHRASE, KEY, KeyMode.KEYFILE, KeyModeMismatchError),
        (PASSPHRASE, OTHER_PASSPHRASE, KeyMode.PASSPHRASE, DecryptionError),
    ],
)
def test_rekey_store_reencrypts_with_the_new_secret_only(
    service: StoreService,
    backend: MemoryBackend,
    case: tuple[Secret, Secret, KeyMode, type[Exception]],
) -> None:
    old, new, mode, old_error = case
    _filled(service, "vault", old)

    service.rekey_store("vault", old=old, new=new)

    assert backend.read("vault").info.key_mode is mode
    assert backend.read("vault").revision == 3
    assert service.read_variables("vault", secret=new) == _VARIABLES
    with pytest.raises(old_error):
        service.read_variables("vault", secret=old)


def test_rekey_with_the_same_passphrase_generates_a_new_salt(
    service: StoreService, backend: MemoryBackend
) -> None:
    _filled(service, "vault", PASSPHRASE)
    before = backend.read("vault").cipher_meta

    service.rekey_store("vault", old=PASSPHRASE, new=PASSPHRASE)

    after = backend.read("vault").cipher_meta
    assert before is not None
    assert after is not None
    assert before.kdf is not None
    assert after.kdf is not None
    assert after.kdf.salt != before.kdf.salt


def test_rekey_with_the_wrong_old_secret_writes_nothing(
    service: StoreService, backend: MemoryBackend
) -> None:
    _filled(service, "vault", KEY)
    before = backend.read("vault")

    with pytest.raises(DecryptionError):
        service.rekey_store("vault", old=OTHER_KEY, new=PASSPHRASE)

    assert backend.read("vault") == before


def test_rekey_a_plaintext_store_raises_not_encrypted(service: StoreService) -> None:
    service.create_store("base")

    with pytest.raises(NotEncryptedError):
        service.rekey_store("base", old=KEY, new=OTHER_KEY)


# --- copy --------------------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, KEY, PASSPHRASE])
def test_copy_store_keeps_the_encryption_and_secret_by_default(
    service: StoreService, backend: MemoryBackend, secret: Secret | None
) -> None:
    _filled(service, "src", secret)

    info = service.copy_store("src", "dst", secret=secret)

    assert info.name == "dst"
    assert info.revision == 1
    assert info.key_mode == backend.read("src").info.key_mode
    assert service.read_variables("dst", secret=secret) == _VARIABLES
    assert service.read_variables("src", secret=secret) == _VARIABLES


def test_copy_store_reencrypts_because_the_ciphertext_is_bound_to_the_name(
    service: StoreService, backend: MemoryBackend
) -> None:
    _filled(service, "src", KEY)

    service.copy_store("src", "dst", secret=KEY)

    assert backend.read("dst").ciphertext != backend.read("src").ciphertext


def test_copy_store_gets_its_own_timestamps(service: StoreService, backend: MemoryBackend) -> None:
    _filled(service, "src", None)

    info = service.copy_store("src", "dst")

    assert info.created_at == info.updated_at
    assert info.created_at > DEFAULT_START
    assert backend.read("src").created_at == DEFAULT_START


@pytest.mark.parametrize("secret", [KEY, PASSPHRASE])
def test_copy_store_plain_makes_an_unencrypted_copy(
    service: StoreService, backend: MemoryBackend, secret: Secret
) -> None:
    _filled(service, "src", secret)

    info = service.copy_store("src", "dst", secret=secret, encryption="plain")

    assert not info.encrypted
    assert dict(backend.read("dst").variables or {}) == _VARIABLES


@pytest.mark.parametrize("source_secret", [None, KEY, PASSPHRASE])
@pytest.mark.parametrize(
    ("new", "mode"), [(OTHER_KEY, KeyMode.KEYFILE), (OTHER_PASSPHRASE, KeyMode.PASSPHRASE)]
)
def test_copy_store_with_a_new_secret_encrypts_the_copy_with_it(
    service: StoreService, source_secret: Secret | None, new: Secret, mode: KeyMode
) -> None:
    _filled(service, "src", source_secret)

    info = service.copy_store("src", "dst", secret=source_secret, encryption=new)

    assert info.key_mode is mode
    assert service.read_variables("dst", secret=new) == _VARIABLES


def test_copy_store_onto_an_existing_store_raises_and_changes_nothing(
    service: StoreService, backend: MemoryBackend
) -> None:
    _filled(service, "src", None)
    service.create_store("dst")
    before = backend.read("dst")

    with pytest.raises(StoreExistsError):
        service.copy_store("src", "dst")

    assert backend.read("dst") == before


def test_copy_store_onto_itself_raises_store_exists(service: StoreService) -> None:
    _filled(service, "src", None)

    with pytest.raises(StoreExistsError):
        service.copy_store("src", "src")


def test_copy_encrypted_store_without_its_key_raises_key_required(
    service: StoreService,
) -> None:
    _filled(service, "src", KEY)

    with pytest.raises(KeyRequiredError):
        service.copy_store("src", "dst", encryption="plain")

    assert [info.name for info in service.list_stores()] == ["src"]


def test_copy_missing_store_raises_store_not_found(service: StoreService) -> None:
    with pytest.raises(StoreNotFoundError):
        service.copy_store("missing", "dst")


def test_copy_store_rejects_an_unknown_encryption_choice(service: StoreService) -> None:
    _filled(service, "src", None)

    with pytest.raises(ValidationError, match="encryption"):
        service.copy_store("src", "dst", encryption=cast("Encryption", "aes"))

    assert [info.name for info in service.list_stores()] == ["src"]


@pytest.mark.parametrize("secret", [None, KEY, PASSPHRASE])
def test_copy_store_to_another_backend_may_keep_the_name(
    service: StoreService, make_service: MakeService, secret: Secret | None
) -> None:
    other = make_service(MemoryBackend().open())
    _filled(service, "src", secret)

    service.copy_store("src", "src", secret=secret, destination=other)

    assert other.read_variables("src", secret=secret) == _VARIABLES
    assert service.read_variables("src", secret=secret) == _VARIABLES


# --- move --------------------------------------------------------------------------------------


@pytest.mark.parametrize("secret", [None, KEY, PASSPHRASE])
def test_move_store_renames_it(service: StoreService, secret: Secret | None) -> None:
    _filled(service, "src", secret)

    info = service.move_store("src", "dst", secret=secret)

    assert info.name == "dst"
    assert [store.name for store in service.list_stores()] == ["dst"]
    assert service.read_variables("dst", secret=secret) == _VARIABLES


def test_move_store_to_another_backend_removes_the_source(
    service: StoreService, make_service: MakeService
) -> None:
    other = make_service(MemoryBackend().open())
    _filled(service, "src", KEY)

    service.move_store("src", "src", secret=KEY, encryption=PASSPHRASE, destination=other)

    assert service.list_stores() == []
    assert other.read_variables("src", secret=PASSPHRASE) == _VARIABLES


def test_move_store_onto_an_existing_store_keeps_the_source(service: StoreService) -> None:
    _filled(service, "src", None)
    service.create_store("dst")

    with pytest.raises(StoreExistsError):
        service.move_store("src", "dst")

    assert service.read_variables("src") == _VARIABLES


def test_move_store_whose_source_cannot_be_deleted_keeps_both_copies(
    backend: MemoryBackend, make_service: MakeService
) -> None:
    _filled(make_service(backend.open()), "src", None)
    service = make_service(FailingDeleteAdapter(backend))

    with pytest.raises(BackendError):
        service.move_store("src", "dst")

    assert [info.name for info in backend.infos()] == ["dst", "src"]


def test_move_store_changed_concurrently_keeps_the_source_and_removes_the_copy(
    backend: MemoryBackend, make_service: MakeService
) -> None:
    _filled(make_service(backend.open()), "src", None)
    service = make_service(RacingAdapter(backend, bump("src")))

    with pytest.raises(ConcurrentModificationError):
        service.move_store("src", "dst")

    assert [info.name for info in backend.infos()] == ["src"]
    assert backend.read("src").revision == 3


def test_move_store_to_another_backend_changed_concurrently_removes_only_the_copy(
    backend: MemoryBackend, make_service: MakeService
) -> None:
    # Same name in both backends: the rollback must delete the copy, not the changed source.
    _filled(make_service(backend.open()), "src", None)
    service = make_service(RacingAdapter(backend, bump("src")))
    other = make_service(MemoryBackend().open())

    with pytest.raises(ConcurrentModificationError):
        service.move_store("src", "src", destination=other)

    assert other.list_stores() == []
    assert [info.name for info in backend.infos()] == ["src"]
    assert backend.read("src").revision == 3


# --- store names are validated before the adapter is touched -----------------------------------

_OPERATIONS: dict[str, Callable[[StoreService, str], object]] = {
    "create": lambda service, name: service.create_store(name),
    "delete": lambda service, name: service.delete_store(name),
    "parse_secret": lambda service, name: service.parse_secret(name, "text"),
    "read": lambda service, name: service.read_variables(name),
    "set": lambda service, name: service.set_variables(name, {"A": "1"}),
    "delete_variables": lambda service, name: service.delete_variables(name, ["A"]),
    "encrypt": lambda service, name: service.encrypt_store(name, secret=KEY),
    "rekey": lambda service, name: service.rekey_store(name, old=KEY, new=OTHER_KEY),
    "copy_source": lambda service, name: service.copy_store(name, "dst"),
    "copy_destination": lambda service, name: service.copy_store("src", name),
    "move_source": lambda service, name: service.move_store(name, "dst"),
    "move_destination": lambda service, name: service.move_store("src", name),
}


@pytest.mark.parametrize("operation", list(_OPERATIONS))
@pytest.mark.parametrize("name", ["../etc", "Upper", "", "a/b", "x" * 64])
def test_every_operation_validates_store_names_before_touching_the_adapter(
    operation: str, name: str
) -> None:
    service = StoreService(UntouchableAdapter(), kdf_params_factory=CheapKdf())

    with pytest.raises(ValidationError, match="store name"):
        _OPERATIONS[operation](service, name)


def test_load_validates_every_source_name_before_touching_the_adapter() -> None:
    service = StoreService(UntouchableAdapter())
    smuggled = Source(name="ok")
    object.__setattr__(smuggled, "name", "../etc")  # bypass Source's own validation

    with pytest.raises(ValidationError, match="store name"):
        service.load([Source(name="fine"), smuggled])
