from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from environment_store.config.settings import resolve_settings
from environment_store.core.adapter import MigrationReport, SetupMode
from environment_store.core.errors import (
    AlreadyEncryptedError,
    BackendError,
    ConfigurationError,
    DecryptionError,
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    KeySourceError,
    NotEncryptedError,
    StoreExistsError,
    StoreNotFoundError,
    ValidationError,
    VariableExistsError,
    VariableNotFoundError,
)
from environment_store.core.merge import MergeOrder
from environment_store.core.models import KeyMode
from environment_store.library.sources import KeyInput, Source
from environment_store.library.store import EnvironmentStore, open_configured_adapter
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend
from tests.unit.library.conftest import (
    CONNECTION,
    KEY,
    OTHER_KEY,
    PASSPHRASE,
    RecordingOpener,
)

# --- construction and lifetime -----------------------------------------------------------------


def test_construction_opens_one_adapter_with_the_connection_and_setup(
    opener: RecordingOpener,
) -> None:
    with EnvironmentStore(CONNECTION, setup=SetupMode.NONE, opener=opener):
        pass

    assert [(url, setup) for url, setup, _ in opener.opened] == [(CONNECTION, SetupMode.NONE)]


def test_setup_defaults_to_auto(opener: RecordingOpener) -> None:
    with EnvironmentStore(CONNECTION, opener=opener):
        pass

    assert opener.opened[0][1] is SetupMode.AUTO


def test_context_manager_closes_the_adapter(opener: RecordingOpener) -> None:
    with EnvironmentStore(CONNECTION, opener=opener) as store:
        assert not store.closed

    assert store.closed
    with pytest.raises(BackendError):
        opener.opened[0][2].list_stores()


def test_close_is_idempotent(store: EnvironmentStore) -> None:
    store.close()
    store.close()

    assert store.closed


def test_exit_does_not_suppress_exceptions(opener: RecordingOpener) -> None:
    with pytest.raises(RuntimeError, match="boom"), EnvironmentStore(CONNECTION, opener=opener):
        raise RuntimeError("boom")  # noqa: EM101 - test exception


@pytest.mark.parametrize(
    "call",
    [
        lambda store: store.list_stores(),
        lambda store: store.store_info("a"),
        lambda store: store.create_store("a"),
        lambda store: store.delete_store("a"),
        lambda store: store.variables("a"),
        lambda store: store.load(["a"]),
        lambda store: store.migrate(),
        lambda store: store.parse_secret("a", "text"),
    ],
)
def test_use_after_close_is_a_validation_error(
    store: EnvironmentStore, call: Callable[[EnvironmentStore], object]
) -> None:
    store.close()

    with pytest.raises(ValidationError, match="closed"):
        call(store)


def test_invalid_connection_string_is_refused_before_opening(opener: RecordingOpener) -> None:
    with pytest.raises(ValidationError, match="scheme://"):
        EnvironmentStore("no scheme", opener=opener)

    assert opener.opened == []


def test_opener_errors_propagate_unchanged(backend: MemoryBackend) -> None:
    def failing(url: str, setup: SetupMode) -> MemoryAdapter:
        message = "database refused"
        raise BackendError(message)

    with pytest.raises(BackendError, match="database refused"):
        EnvironmentStore(CONNECTION, opener=failing)


def test_repr_shows_the_scheme_but_never_the_connection(opener: RecordingOpener) -> None:
    with EnvironmentStore("memory://user:hunter2@host/db", opener=opener) as store:
        assert repr(store) == "EnvironmentStore(scheme='memory')"


def test_from_env_reads_the_connection_variable(opener: RecordingOpener) -> None:
    environ = {"ENV_STORE_CONNECTION": CONNECTION}

    with EnvironmentStore.from_env(environ=environ, opener=opener, setup=SetupMode.NONE):
        pass

    assert opener.opened[0][:2] == (CONNECTION, SetupMode.NONE)


@pytest.mark.parametrize("environ", [{}, {"ENV_STORE_CONNECTION": ""}])
def test_from_env_without_the_variable_is_a_configuration_error(
    opener: RecordingOpener, environ: dict[str, str]
) -> None:
    with pytest.raises(ConfigurationError, match="ENV_STORE_CONNECTION"):
        EnvironmentStore.from_env(environ=environ, opener=opener)


def test_from_env_defaults_to_the_process_environment(
    opener: RecordingOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENV_STORE_CONNECTION", "memory://from-process")

    with EnvironmentStore.from_env(opener=opener):
        pass

    assert opener.opened[0][0] == "memory://from-process"


def test_from_settings_uses_the_resolved_connection(
    opener: RecordingOpener, tmp_path: Path
) -> None:
    settings = resolve_settings(connection=CONNECTION, use_project=False, environ={}, cwd=tmp_path)

    with EnvironmentStore.from_settings(settings, opener=opener):
        pass

    assert opener.opened[0][0] == CONNECTION


def test_from_settings_without_connection_is_a_configuration_error(
    opener: RecordingOpener, tmp_path: Path
) -> None:
    settings = resolve_settings(connection=None, use_project=False, environ={}, cwd=tmp_path)

    with pytest.raises(ConfigurationError, match="-c/--connection"):
        EnvironmentStore.from_settings(settings, opener=opener)
    assert opener.opened == []


# --- stores ------------------------------------------------------------------------------------


def test_create_list_info_and_delete_a_plaintext_store(store: EnvironmentStore) -> None:
    info = store.create_store("base")

    assert not info.encrypted
    assert store.list_stores() == [info]
    assert store.store_info("base") == info
    store.delete_store("base")
    assert store.list_stores() == []


def test_store_info_of_a_missing_store(store: EnvironmentStore) -> None:
    with pytest.raises(StoreNotFoundError):
        store.store_info("missing")


def test_store_info_validates_the_name(store: EnvironmentStore) -> None:
    with pytest.raises(ValidationError):
        store.store_info("Bad Name")


@pytest.mark.parametrize(
    ("key", "mode"),
    [(None, KeyMode.KEYFILE), (KEY, KeyMode.KEYFILE), (PASSPHRASE, KeyMode.PASSPHRASE)],
)
def test_create_an_encrypted_store(
    store: EnvironmentStore, key_file: Path, key: KeyInput | None, mode: KeyMode
) -> None:
    # None stands for the key file fixture.
    info = store.create_store("secret", encrypt=True, key=key_file if key is None else key)

    assert info.key_mode is mode


def test_create_with_a_key_file_path_uses_that_key(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("secret", encrypt=True, key=key_file)
    store.set("secret", "A", "1", key=KEY)

    assert store.variables("secret", key=key_file) == {"A": "1"}


def test_create_with_a_passphrase_file_path_is_refused(
    store: EnvironmentStore, passphrase_file: Path
) -> None:
    with pytest.raises(InvalidKeyFileError):
        store.create_store("secret", encrypt=True, key=passphrase_file)


def test_create_encrypted_without_key_is_a_validation_error(store: EnvironmentStore) -> None:
    with pytest.raises(ValidationError, match="key"):
        store.create_store("secret", encrypt=True)


def test_create_with_key_but_without_encrypt_is_a_validation_error(
    store: EnvironmentStore,
) -> None:
    with pytest.raises(ValidationError, match="encrypt=True"):
        store.create_store("secret", key=KEY)


def test_create_refuses_a_plain_string_key(store: EnvironmentStore) -> None:
    with pytest.raises(ValidationError, match="plain string"):
        store.create_store("secret", encrypt=True, key="words")  # ty: ignore[invalid-argument-type] - the point


def test_create_an_existing_store(store: EnvironmentStore) -> None:
    store.create_store("base")

    with pytest.raises(StoreExistsError):
        store.create_store("base")


# --- variables ---------------------------------------------------------------------------------


def test_set_get_variables_and_delete_on_a_plaintext_store(store: EnvironmentStore) -> None:
    store.create_store("base")
    store.set("base", "B", "2")
    store.set_many("base", {"A": "1", "C": "3"})
    store.delete("base", ["C"])

    assert store.get("base", "A") == "1"
    assert store.variables("base") == {"A": "1", "B": "2"}


def test_set_refuses_existing_variables_without_overwrite(store: EnvironmentStore) -> None:
    store.create_store("base")
    store.set("base", "A", "1")

    with pytest.raises(VariableExistsError):
        store.set("base", "A", "2")
    store.set("base", "A", "2", overwrite=True)
    assert store.get("base", "A") == "2"


def test_set_many_with_overwrite(store: EnvironmentStore) -> None:
    store.create_store("base")
    store.set_many("base", {"A": "1"})

    store.set_many("base", {"A": "2", "B": "3"}, overwrite=True)

    assert store.variables("base") == {"A": "2", "B": "3"}


def test_get_of_a_missing_variable_raises_variable_not_found(store: EnvironmentStore) -> None:
    store.create_store("base")

    with pytest.raises(VariableNotFoundError) as caught:
        store.get("base", "MISSING")
    assert caught.value.names == ("MISSING",)


def test_get_validates_the_variable_name(store: EnvironmentStore) -> None:
    store.create_store("base")

    with pytest.raises(ValidationError):
        store.get("base", "not valid")


@pytest.mark.parametrize("key", ["path", "material"])
def test_variables_of_a_keyfile_store_by_path_or_key(
    store: EnvironmentStore, key_file: Path, key: str
) -> None:
    store.create_store("secret", encrypt=True, key=KEY)
    secret = key_file if key == "path" else KEY
    store.set("secret", "A", "1", key=secret)
    store.set_many("secret", {"B": "2"}, key=secret)
    store.delete("secret", ["B"], key=secret)

    assert store.get("secret", "A", key=secret) == "1"
    assert store.variables("secret", key=secret) == {"A": "1"}


def test_variables_of_a_passphrase_store_by_file(
    store: EnvironmentStore, passphrase_file: Path
) -> None:
    store.create_store("secret", encrypt=True, key=PASSPHRASE)
    store.set("secret", "A", "1", key=passphrase_file)

    assert store.variables("secret", key=PASSPHRASE) == {"A": "1"}


def test_encrypted_store_without_key(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(KeyRequiredError):
        store.variables("secret")


def test_key_for_a_plaintext_store(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("base")

    with pytest.raises(NotEncryptedError):
        store.variables("base", key=key_file)
    with pytest.raises(NotEncryptedError):
        store.variables("base", key=KEY)


def test_key_file_for_a_passphrase_store(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("secret", encrypt=True, key=PASSPHRASE)

    with pytest.raises(KeyModeMismatchError):
        store.variables("secret", key=key_file)


def test_variables_with_a_missing_key_file_raises_key_source_error(
    store: EnvironmentStore, tmp_path: Path
) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(KeySourceError):
        store.variables("secret", key=tmp_path / "missing.key")


def test_variables_with_a_wrong_key_raises_decryption_error(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(DecryptionError):
        store.variables("secret", key=OTHER_KEY)


def test_variables_refuse_a_plain_string_key(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(ValidationError, match="plain string"):
        store.variables("secret", key="a.key")  # ty: ignore[invalid-argument-type] - the point


# --- encryption --------------------------------------------------------------------------------


def test_encrypt_store_with_a_key_file(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("base")
    store.set("base", "A", "1")

    store.encrypt_store("base", key=key_file)

    assert store.store_info("base").key_mode is KeyMode.KEYFILE
    assert store.variables("base", key=KEY) == {"A": "1"}


def test_encrypt_an_encrypted_store(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(AlreadyEncryptedError):
        store.encrypt_store("secret", key=OTHER_KEY)


def test_rekey_store_switches_to_a_passphrase(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("secret", encrypt=True, key=KEY)
    store.set("secret", "A", "1", key=KEY)

    store.rekey_store("secret", old=key_file, new=PASSPHRASE)

    assert store.store_info("secret").key_mode is KeyMode.PASSPHRASE
    assert store.variables("secret", key=PASSPHRASE) == {"A": "1"}


def test_rekey_store_new_path_must_be_a_key_file(
    store: EnvironmentStore, passphrase_file: Path
) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(InvalidKeyFileError):
        store.rekey_store("secret", old=KEY, new=passphrase_file)


def test_secret_for_reads_a_path_by_the_store_mode(
    store: EnvironmentStore, passphrase_file: Path
) -> None:
    store.create_store("secret", encrypt=True, key=PASSPHRASE)

    assert store.secret_for("secret", passphrase_file) == PASSPHRASE
    assert store.secret_for("secret", PASSPHRASE) == PASSPHRASE


def test_parse_secret_interprets_text_by_the_store_mode(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=PASSPHRASE)

    assert store.parse_secret("secret", f"{PASSPHRASE.text}\n") == PASSPHRASE


# --- copy and move -----------------------------------------------------------------------------


def test_copy_store_keeps_the_encryption_by_default(
    store: EnvironmentStore, key_file: Path
) -> None:
    store.create_store("src", encrypt=True, key=KEY)
    store.set("src", "A", "1", key=KEY)

    info = store.copy_store("src", "dst", key=key_file)

    assert info.key_mode is KeyMode.KEYFILE
    assert store.variables("dst", key=KEY) == {"A": "1"}
    assert store.variables("src", key=KEY) == {"A": "1"}


def test_copy_store_plain_makes_an_unencrypted_copy(store: EnvironmentStore) -> None:
    store.create_store("src", encrypt=True, key=KEY)
    store.set("src", "A", "1", key=KEY)

    info = store.copy_store("src", "dst", key=KEY, encryption="plain")

    assert not info.encrypted
    assert store.variables("dst") == {"A": "1"}


@pytest.mark.parametrize("new", [None, OTHER_KEY, PASSPHRASE])
def test_copy_store_with_a_new_secret(
    store: EnvironmentStore, other_key_file: Path, new: KeyInput | None
) -> None:
    store.create_store("src")
    store.set("src", "A", "1")
    # None stands for the other key file fixture.
    encryption = other_key_file if new is None else new

    store.copy_store("src", "dst", encryption=encryption)

    expected = PASSPHRASE if new is PASSPHRASE else OTHER_KEY
    assert store.variables("dst", key=expected) == {"A": "1"}


def test_copy_store_refuses_an_unknown_encryption(store: EnvironmentStore) -> None:
    store.create_store("src")

    with pytest.raises(ValidationError, match="encryption"):
        store.copy_store("src", "dst", encryption="other")  # ty: ignore[invalid-argument-type] - the point


def test_copy_store_into_another_backend(
    store: EnvironmentStore, clock: object, kdf: CheapKdf
) -> None:
    store.create_store("src")
    store.set("src", "A", "1")
    other = MemoryBackend()

    with EnvironmentStore(
        CONNECTION, opener=lambda _url, setup: other.open(setup=setup), kdf_params_factory=kdf
    ) as target:
        store.copy_store("src", "src", to=target)

        assert target.variables("src") == {"A": "1"}


def test_copy_store_into_a_closed_target_is_refused(
    store: EnvironmentStore, make_store: Callable[[], EnvironmentStore]
) -> None:
    store.create_store("src")
    target = make_store()
    target.close()

    with pytest.raises(ValidationError, match="closed"):
        store.copy_store("src", "dst", to=target)


def test_move_store_renames(store: EnvironmentStore) -> None:
    store.create_store("src")
    store.set("src", "A", "1")

    info = store.move_store("src", "dst")

    assert info.name == "dst"
    assert [entry.name for entry in store.list_stores()] == ["dst"]


def test_move_store_into_another_backend_with_a_new_key(
    store: EnvironmentStore, kdf: CheapKdf
) -> None:
    store.create_store("src", encrypt=True, key=KEY)
    store.set("src", "A", "1", key=KEY)
    other = MemoryBackend()

    with EnvironmentStore(
        CONNECTION, opener=lambda _url, setup: other.open(setup=setup), kdf_params_factory=kdf
    ) as target:
        store.move_store("src", "src", key=KEY, encryption=PASSPHRASE, to=target)

        assert target.variables("src", key=PASSPHRASE) == {"A": "1"}
    assert store.list_stores() == []


# --- load --------------------------------------------------------------------------------------


def test_load_merges_sources_in_order(store: EnvironmentStore, key_file: Path) -> None:
    store.create_store("base")
    store.set_many("base", {"HOST": "localhost", "PORT": "1"})
    store.create_store("secret", encrypt=True, key=KEY)
    store.set("secret", "HOST", "secret-host", key=KEY)

    environment = store.load(["base", Source("secret", key=key_file)])

    assert environment.order is MergeOrder.LAST_WINS
    assert environment.variables() == {"HOST": "secret-host", "PORT": "1"}
    assert [name for name, _ in environment.stores] == ["base", "secret"]


def test_load_first_wins_keeps_the_first_value(store: EnvironmentStore) -> None:
    store.create_store("a")
    store.set("a", "X", "a")
    store.create_store("b")
    store.set("b", "X", "b")

    environment = store.load([Source("a"), "b"], order=MergeOrder.FIRST_WINS)

    assert environment.variables() == {"X": "a"}


def test_load_without_key_for_an_encrypted_store(store: EnvironmentStore) -> None:
    store.create_store("secret", encrypt=True, key=KEY)

    with pytest.raises(KeyRequiredError):
        store.load(["secret"])


def test_load_refuses_something_that_is_no_source(store: EnvironmentStore) -> None:
    with pytest.raises(ValidationError, match="Source or a store name"):
        store.load([Path("a")])  # ty: ignore[invalid-argument-type] - the point


def test_load_refuses_a_single_string(store: EnvironmentStore) -> None:
    store.create_store("a")

    with pytest.raises(ValidationError, match="list"):
        store.load("a")


# --- migrate -----------------------------------------------------------------------------------


class _MigratingAdapter(MemoryAdapter):
    def migrate(self) -> MigrationReport:
        return MigrationReport(from_version=None, to_version=1, created=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def test_migrate_runs_the_adapter_migration() -> None:
    with EnvironmentStore(CONNECTION, opener=lambda _url, _setup: _MigratingAdapter()) as store:
        assert store.migrate() == MigrationReport(from_version=None, to_version=1, created=True)


def test_migrate_on_a_backend_without_schema_is_a_validation_error(
    store: EnvironmentStore,
) -> None:
    with pytest.raises(ValidationError, match=r"'memory'.*no schema"):
        store.migrate()


# --- real schemes through the default opener ---------------------------------------------------


@pytest.mark.parametrize("scheme", ["json", "toml"])
def test_file_backends_through_the_default_opener(tmp_path: Path, scheme: str) -> None:
    with EnvironmentStore(f"{scheme}://{tmp_path / 'envs'}") as store:
        store.create_store("base")
        store.set("base", "A", "1")

        assert store.variables("base") == {"A": "1"}
        with pytest.raises(ValidationError, match="no schema"):
            store.migrate()


def test_sqlite_through_the_default_opener(tmp_path: Path) -> None:
    with EnvironmentStore(f"sqlite:///{tmp_path / 'envs.db'}", setup=SetupMode.NONE) as store:
        report = store.migrate()
        store.create_store("base")

        assert report.created
        assert [info.name for info in store.list_stores()] == ["base"]


def test_open_configured_adapter_uses_the_registry(tmp_path: Path) -> None:
    with open_configured_adapter(f"json://{tmp_path}", SetupMode.AUTO) as adapter:
        assert adapter.list_stores() == []


def test_passphrase_with_the_spec_kdf_defaults(tmp_path: Path) -> None:
    # The one library test with the real Argon2id parameters (t=3, m=64 MiB, p=4).
    with EnvironmentStore(f"json://{tmp_path}") as store:
        store.create_store("secret", encrypt=True, key=PASSPHRASE)
        store.set("secret", "A", "1", key=PASSPHRASE)

        assert store.variables("secret", key=PASSPHRASE) == {"A": "1"}
