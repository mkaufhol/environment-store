"""Exit codes by error category (D24)."""

import pytest

from environment_store.cli.errors import ExitCode, exit_code_for
from environment_store.core import errors
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

_EXPECTED: dict[type[EnvironmentStoreError], ExitCode] = {
    EnvironmentStoreError: ExitCode.USAGE,
    ValidationError: ExitCode.USAGE,
    AlreadyEncryptedError: ExitCode.USAGE,
    NotEncryptedError: ExitCode.USAGE,
    PlaintextNotAllowedError: ExitCode.USAGE,
    ConfigurationError: ExitCode.USAGE,
    MissingExtraError: ExitCode.USAGE,
    BackendError: ExitCode.USAGE,
    UnsupportedFormatError: ExitCode.USAGE,
    DatabaseNotCleanError: ExitCode.USAGE,
    SchemaOutdatedError: ExitCode.USAGE,
    SchemaTooNewError: ExitCode.USAGE,
    SetupPrivilegeError: ExitCode.USAGE,
    NotFoundError: ExitCode.NOT_FOUND,
    StoreNotFoundError: ExitCode.NOT_FOUND,
    VariableNotFoundError: ExitCode.NOT_FOUND,
    AlreadyExistsError: ExitCode.EXISTS,
    StoreExistsError: ExitCode.EXISTS,
    VariableExistsError: ExitCode.EXISTS,
    CryptoError: ExitCode.KEY,
    KeyRequiredError: ExitCode.KEY,
    DecryptionError: ExitCode.KEY,
    InvalidKeyFileError: ExitCode.KEY,
    KeyModeMismatchError: ExitCode.KEY,
    KeySourceError: ExitCode.KEY,
    ConcurrentModificationError: ExitCode.CONFLICT,
}


def _instance(cls: type[EnvironmentStoreError]) -> EnvironmentStoreError:
    if issubclass(cls, MissingExtraError):
        return cls("cli")
    if issubclass(cls, (VariableNotFoundError, VariableExistsError)):
        return cls(["A"], store="s")
    return cls("message")


def test_exit_codes_have_the_spec_values() -> None:
    assert [int(code) for code in ExitCode] == [0, 1, 2, 3, 4, 5]
    assert [code.name for code in ExitCode] == [
        "OK",
        "USAGE",
        "NOT_FOUND",
        "EXISTS",
        "KEY",
        "CONFLICT",
    ]


def test_table_covers_every_error_class() -> None:
    assert {getattr(errors, name) for name in errors.__all__} == set(_EXPECTED)


@pytest.mark.parametrize(("cls", "code"), _EXPECTED.items(), ids=str)
def test_error_class_maps_to_its_category_exit_code(
    cls: type[EnvironmentStoreError], code: ExitCode
) -> None:
    assert exit_code_for(_instance(cls)) is code
