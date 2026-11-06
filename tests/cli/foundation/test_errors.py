"""Exit codes by error category (D24)."""

from pathlib import Path

import pytest

from environment_store.cli.errors import ExitCode, exit_code_for, message_for
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
from environment_store.crypto.keyfile import parse_key
from environment_store.formats.dotenv import DotenvValueError
from environment_store.formats.dotenv import dumps as dotenv_dumps
from environment_store.library.files import OutputFileExistsError

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


# --- CLI hints instead of library parameters (D47) ---------------------------------------------


def test_existing_variables_name_the_overwrite_option() -> None:
    error = VariableExistsError(["A", "B"], store="a")

    assert message_for(error) == (
        "variables already exist in store 'a': A, B; use -o/--overwrite to replace them"
    )


def test_existing_output_file_names_the_force_option() -> None:
    error = OutputFileExistsError(Path(".env"))

    assert message_for(error) == "output file '.env' already exists; use --force to replace it"


def test_dotenv_refusal_names_the_type_option_and_run() -> None:
    with pytest.raises(DotenvValueError) as caught:
        dotenv_dumps({"TOKEN": "${HOME}"})

    message = message_for(caught.value)
    assert message.startswith(caught.value.detail)
    assert message.endswith("; export with -t json or -t toml, or use envs run instead")
    assert "fmt=" not in message


def test_invalid_key_file_names_keygen() -> None:
    with pytest.raises(InvalidKeyFileError) as caught:
        parse_key("not a key")

    message = message_for(caught.value)
    assert message.startswith(caught.value.detail)
    assert message.endswith("; create one with envs keygen")
    assert "generate_key" not in message


def test_missing_key_names_the_key_option() -> None:
    assert message_for(KeyRequiredError.for_store("prod")) == (
        "store 'prod' is encrypted and no key or passphrase was given; "
        "pass it with -k <path> (or -k - for stdin)"
    )


@pytest.mark.parametrize(
    "error",
    [
        KeyRequiredError("store 'p' is encrypted: pass it with -k p=<path>"),
        ValidationError("bad", hint="pass fmt='json'"),
        StoreNotFoundError("store 'x' does not exist"),
    ],
    ids=["cli-worded", "unmapped-hint", "no-hint"],
)
def test_other_errors_keep_their_message(error: EnvironmentStoreError) -> None:
    assert message_for(error) == str(error)
