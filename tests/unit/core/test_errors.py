import pytest

from environment_store.core.errors import (
    AlreadyEncryptedError,
    AlreadyExistsError,
    BackendError,
    ConcurrentModificationError,
    ConfigurationError,
    CryptoError,
    DatabaseNotCleanError,
    DecryptionError,
    EnvironmentStoreError,
    InvalidKeyFileError,
    KeyModeMismatchError,
    KeyRequiredError,
    KeySourceError,
    MissingExtraError,
    NotEncryptedError,
    NotFoundError,
    PlaintextNotAllowedError,
    SchemaOutdatedError,
    SchemaTooNewError,
    SetupPrivilegeError,
    StoreExistsError,
    StoreNotFoundError,
    UnsupportedFormatError,
    ValidationError,
    VariableExistsError,
    VariableNotFoundError,
)

# The category classes are what the CLI maps to exit codes (D24).
_CATEGORIES: list[type[EnvironmentStoreError]] = [
    ValidationError,
    ConfigurationError,
    MissingExtraError,
    BackendError,
    NotFoundError,
    AlreadyExistsError,
    CryptoError,
    ConcurrentModificationError,
]

_CONCRETE: list[tuple[type[EnvironmentStoreError], type[EnvironmentStoreError]]] = [
    (AlreadyEncryptedError, ValidationError),
    (NotEncryptedError, ValidationError),
    (PlaintextNotAllowedError, ValidationError),
    (UnsupportedFormatError, BackendError),
    (DatabaseNotCleanError, BackendError),
    (SchemaOutdatedError, BackendError),
    (SchemaTooNewError, BackendError),
    (SetupPrivilegeError, BackendError),
    (StoreNotFoundError, NotFoundError),
    (VariableNotFoundError, NotFoundError),
    (StoreExistsError, AlreadyExistsError),
    (VariableExistsError, AlreadyExistsError),
    (KeyRequiredError, CryptoError),
    (DecryptionError, CryptoError),
    (InvalidKeyFileError, CryptoError),
    (KeyModeMismatchError, CryptoError),
    (KeySourceError, CryptoError),
]


def test_root_error_is_an_exception() -> None:
    assert issubclass(EnvironmentStoreError, Exception)


@pytest.mark.parametrize("category", _CATEGORIES)
def test_every_category_derives_directly_from_the_root_error(
    category: type[EnvironmentStoreError],
) -> None:
    assert EnvironmentStoreError in category.__bases__


def test_validation_error_is_also_a_value_error() -> None:
    assert issubclass(ValidationError, ValueError)


@pytest.mark.parametrize(("error", "category"), _CONCRETE)
def test_concrete_error_belongs_to_its_exit_code_category(
    error: type[EnvironmentStoreError], category: type[EnvironmentStoreError]
) -> None:
    assert issubclass(error, category)


def test_concrete_errors_belong_to_exactly_one_category() -> None:
    for error, _ in _CONCRETE:
        assert sum(issubclass(error, category) for category in _CATEGORIES) == 1


def test_missing_extra_error_names_the_extra_and_the_install_command() -> None:
    error = MissingExtraError("postgres")

    assert error.extra == "postgres"
    assert "pip install 'environment-store[postgres]'" in str(error)


def test_variable_not_found_error_lists_all_missing_names() -> None:
    error = VariableNotFoundError(["B", "A"], store="base")

    assert error.names == ("B", "A")
    assert error.store == "base"
    assert str(error) == "variables not found in store 'base': B, A"


def test_variable_exists_error_lists_all_conflicting_names() -> None:
    error = VariableExistsError(("DB_HOST",), store="base")

    assert error.names == ("DB_HOST",)
    assert error.store == "base"
    assert str(error) == (
        "variables already exist in store 'base': DB_HOST (use overwrite to replace them)"
    )
