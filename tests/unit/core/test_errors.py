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


def test_missing_extra_error_names_the_extra_and_the_install_commands_uv_first() -> None:
    error = MissingExtraError("postgres")

    assert error.extra == "postgres"
    assert str(error) == (
        "this feature needs the optional 'postgres' dependencies: "
        "uv add 'environment-store[postgres]' (or pip install 'environment-store[postgres]'); "
        "for the CLI tool: uv tool install 'environment-store[cli,postgres]'"
    )


def test_missing_cli_extra_does_not_name_cli_twice_in_the_tool_command() -> None:
    error = MissingExtraError("cli")

    assert str(error).endswith("for the CLI tool: uv tool install 'environment-store[cli]'")
    assert "cli,cli" not in str(error)


def test_variable_not_found_error_lists_all_missing_names() -> None:
    error = VariableNotFoundError(["B", "A"], store="base")

    assert error.names == ("B", "A")
    assert error.store == "base"
    assert str(error) == "variables not found in store 'base': B, A"


def test_variable_not_found_error_for_one_name_is_singular() -> None:
    error = VariableNotFoundError(["A"], store="base")

    assert str(error) == "variable 'A' not found in store 'base'"


def test_variable_exists_error_lists_all_conflicting_names() -> None:
    error = VariableExistsError(("DB_HOST",), store="base")

    assert error.names == ("DB_HOST",)
    assert error.store == "base"
    assert error.detail == "variables already exist in store 'base': DB_HOST"
    assert error.hint == "pass overwrite=True to replace them"
    assert str(error) == f"{error.detail}; {error.hint}"


def test_an_error_without_hint_is_its_detail() -> None:
    error = StoreNotFoundError("store 'x' does not exist")

    assert error.detail == "store 'x' does not exist"
    assert error.hint is None
    assert str(error) == "store 'x' does not exist"


def test_an_error_with_a_hint_appends_it_to_the_detail() -> None:
    error = ValidationError("bad input", hint="pass fmt='json'")

    assert error.detail == "bad input"
    assert error.hint == "pass fmt='json'"
    assert str(error) == "bad input; pass fmt='json'"


def test_key_required_for_a_store_names_the_library_key_parameters() -> None:
    error = KeyRequiredError.for_store("prod")

    assert isinstance(error, KeyRequiredError)
    assert error.detail == "store 'prod' is encrypted and no key or passphrase was given"
    assert error.hint == (
        "pass key=... (or keys={'prod': ...} to load()), or set ENV_STORE_KEY_PROD"
    )
    assert error.store == "prod"


def test_key_required_for_a_store_names_its_key_variable_in_screaming_snake_case() -> None:
    error = KeyRequiredError.for_store("customer-a")

    assert error.hint is not None
    assert error.hint.endswith("or set ENV_STORE_KEY_CUSTOMER_A")


def test_a_key_required_error_without_a_store_has_none() -> None:
    assert KeyRequiredError("no key").store is None
