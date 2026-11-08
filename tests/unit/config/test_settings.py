import dataclasses
import os
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from environment_store.config.load_spec import LoadSpec
from environment_store.config.project import PROJECT_FILE_NAME, ProjectFileCandidate
from environment_store.config.settings import (
    ENV_CONNECTION,
    ENV_ORDERED_OVERWRITE,
    ConnectionSource,
    CredentialsInProjectFileWarning,
    Settings,
    resolve_settings,
)
from environment_store.core.errors import ConfigurationError, ValidationError
from environment_store.core.merge import MergeOrder
from environment_store.core.secrets import Passphrase

_HIDDEN: Final = "hunter2-very-secret"
_FILE_CONNECTION: Final = "postgresql://file-host/db"
_ENV_CONNECTION: Final = "postgresql://env-host/db"
_OPTION_CONNECTION: Final = "postgresql://option-host/db"


def _project(directory: Path, text: str) -> Path:
    path = directory / PROJECT_FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


def _resolve(
    tmp_path: Path,
    *,
    connection: str | None = None,
    environ: dict[str, str] | None = None,
    use_project: bool = True,
    uid: int | None = None,
) -> Settings:
    return resolve_settings(
        connection=connection,
        use_project=use_project,
        environ={} if environ is None else environ,
        cwd=tmp_path,
        boundary=tmp_path,
        uid=uid,
    )


def test_environment_variable_names_use_the_env_store_prefix() -> None:
    assert ENV_CONNECTION == "ENV_STORE_CONNECTION"
    assert ENV_ORDERED_OVERWRITE == "ENV_STORE_ORDERED_OVERWRITE"


def test_credentials_warning_is_a_user_warning() -> None:
    assert issubclass(CredentialsInProjectFileWarning, UserWarning)


# --- connection precedence ---------------------------------------------------------------------


_EXPECTED_CONNECTION: Final = {
    ConnectionSource.OPTION: _OPTION_CONNECTION,
    ConnectionSource.ENVIRONMENT: _ENV_CONNECTION,
    ConnectionSource.PROJECT_FILE: _FILE_CONNECTION,
}


@pytest.mark.parametrize(
    ("option", "env", "file", "source"),
    [
        (_OPTION_CONNECTION, _ENV_CONNECTION, _FILE_CONNECTION, ConnectionSource.OPTION),
        (_OPTION_CONNECTION, _ENV_CONNECTION, None, ConnectionSource.OPTION),
        (_OPTION_CONNECTION, None, _FILE_CONNECTION, ConnectionSource.OPTION),
        (_OPTION_CONNECTION, None, None, ConnectionSource.OPTION),
        (None, _ENV_CONNECTION, _FILE_CONNECTION, ConnectionSource.ENVIRONMENT),
        (None, _ENV_CONNECTION, None, ConnectionSource.ENVIRONMENT),
        (None, None, _FILE_CONNECTION, ConnectionSource.PROJECT_FILE),
        (None, None, None, None),
    ],
)
def test_connection_precedence_option_then_environment_then_project_file(
    tmp_path: Path,
    option: str | None,
    env: str | None,
    file: str | None,
    source: ConnectionSource | None,
) -> None:
    if file is not None:
        _project(tmp_path, f'connection = "{file}"\n')

    settings = _resolve(
        tmp_path, connection=option, environ={} if env is None else {ENV_CONNECTION: env}
    )

    assert settings.connection == (None if source is None else _EXPECTED_CONNECTION[source])
    assert settings.connection_source == source


def test_empty_connection_variable_counts_as_unset(tmp_path: Path) -> None:
    _project(tmp_path, f'connection = "{_FILE_CONNECTION}"\n')

    settings = _resolve(tmp_path, environ={ENV_CONNECTION: ""})

    assert settings.connection == _FILE_CONNECTION


def test_empty_connection_option_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="connection"):
        _resolve(tmp_path, connection="")


def test_require_connection_returns_the_connection(tmp_path: Path) -> None:
    settings = _resolve(tmp_path, connection=_OPTION_CONNECTION)

    assert settings.require_connection() == _OPTION_CONNECTION


def test_missing_connection_names_the_three_ways_to_set_one(tmp_path: Path) -> None:
    settings = _resolve(tmp_path)

    with pytest.raises(ConfigurationError) as caught:
        settings.require_connection()

    message = str(caught.value)
    assert "-c/--connection" in message
    assert "ENV_STORE_CONNECTION" in message
    assert "'connection' in .envstore.toml" in message


def test_repr_hides_the_connection(tmp_path: Path) -> None:
    settings = _resolve(tmp_path, connection=f"postgresql://u:{_HIDDEN}@host/db")

    assert _HIDDEN not in repr(settings)


# --- merge order precedence --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first_wins", "env", "file", "expected"),
    [
        (True, "true", "true", MergeOrder.FIRST_WINS),
        (True, None, None, MergeOrder.FIRST_WINS),
        (False, "false", "true", MergeOrder.FIRST_WINS),
        (False, "true", "false", MergeOrder.LAST_WINS),
        (False, "false", None, MergeOrder.FIRST_WINS),
        (False, None, "false", MergeOrder.FIRST_WINS),
        (False, None, "true", MergeOrder.LAST_WINS),
        (False, "", "false", MergeOrder.FIRST_WINS),
        (False, None, None, MergeOrder.LAST_WINS),
    ],
)
def test_merge_order_precedence_flag_then_environment_then_project_file_then_default(
    tmp_path: Path,
    first_wins: bool,  # noqa: FBT001 - parametrised table column
    env: str | None,
    file: str | None,
    expected: MergeOrder,
) -> None:
    if file is not None:
        _project(tmp_path, f"ordered_overwrite = {file}\n")

    settings = _resolve(tmp_path, environ={} if env is None else {ENV_ORDERED_OVERWRITE: env})

    assert settings.merge_order(first_wins=first_wins) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("YES", True), ("1", True), ("False", False), ("no", False), ("0", False)],
)
def test_ordered_overwrite_variable_accepts_bool_spellings(
    tmp_path: Path,
    raw: str,
    expected: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    settings = _resolve(tmp_path, environ={ENV_ORDERED_OVERWRITE: raw})

    assert settings.ordered_overwrite is expected


def test_invalid_ordered_overwrite_variable_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=ENV_ORDERED_OVERWRITE):
        _resolve(tmp_path, environ={ENV_ORDERED_OVERWRITE: "maybe"})


# --- project file contents ---------------------------------------------------------------------


def test_project_file_supplies_stores_keys_and_its_path(tmp_path: Path) -> None:
    path = _project(tmp_path, 'stores = ["a", "b"]\n[keys]\nb = "b.key"\n')

    settings = _resolve(tmp_path)

    assert settings.stores == ("a", "b")
    assert dict(settings.key_paths) == {"b": tmp_path / "b.key"}
    assert settings.project_file == path
    assert settings.warnings == ()


def test_no_project_ignores_the_file(tmp_path: Path) -> None:
    _project(tmp_path, f'stores = ["a"]\nconnection = "postgresql://u:{_HIDDEN}@h/db"\n')

    settings = _resolve(tmp_path, use_project=False)

    assert settings.stores == ()
    assert settings.connection is None
    assert settings.project_file is None
    assert settings.warnings == ()


def test_no_project_file_gives_empty_defaults(tmp_path: Path) -> None:
    settings = _resolve(tmp_path)

    assert settings.stores == ()
    assert dict(settings.key_paths) == {}
    assert settings.project_file is None
    assert settings.ordered_overwrite is True


# --- load specification (ENV_STORE_LOAD) ----------------------------------------------------------


def test_load_spec_gives_the_default_stores(tmp_path: Path) -> None:
    spec = LoadSpec(stores=("base", "app"), keys={"app": Passphrase(text=_HIDDEN)})

    settings = _resolve(tmp_path, environ={"ENV_STORE_LOAD": spec.encode()})

    assert settings.load_spec == spec
    assert settings.default_stores == ("base", "app")
    assert settings.stores == ()
    assert _HIDDEN not in repr(settings)


def test_load_spec_stores_win_over_the_project_file_stores(tmp_path: Path) -> None:
    _project(tmp_path, 'stores = ["from-file"]\n')
    spec = LoadSpec(stores=("from-env",))

    settings = _resolve(tmp_path, environ={"ENV_STORE_LOAD": spec.encode()})

    assert settings.default_stores == ("from-env",)
    assert settings.stores == ("from-file",)


@pytest.mark.parametrize("environ", [{}, {"ENV_STORE_LOAD": ""}])
def test_without_a_load_spec_the_project_file_gives_the_default_stores(
    tmp_path: Path, environ: dict[str, str]
) -> None:
    _project(tmp_path, 'stores = ["from-file"]\n')

    settings = _resolve(tmp_path, environ=environ)

    assert settings.load_spec is None
    assert settings.default_stores == ("from-file",)


def test_malformed_load_spec_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"^ENV_STORE_LOAD is not a valid") as caught:
        _resolve(tmp_path, environ={"ENV_STORE_LOAD": _HIDDEN})

    assert _HIDDEN not in str(caught.value)


def test_broken_project_file_is_a_configuration_error(tmp_path: Path) -> None:
    _project(tmp_path, "stores = \n")

    with pytest.raises(ConfigurationError, match="not valid TOML"):
        _resolve(tmp_path)


def test_settings_freeze_the_key_paths(tmp_path: Path) -> None:
    _project(tmp_path, '[keys]\na = "a.key"\n')
    settings = _resolve(tmp_path)

    assert isinstance(settings.key_paths, MappingProxyType)


def test_project_file_is_parsed_from_the_bytes_read_at_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What is parsed is what the trust check saw, not whatever the path names later.
    path = _project(tmp_path, 'stores = ["on_disk"]\n')

    def found(*_args: object, **_kwargs: object) -> ProjectFileCandidate:
        return ProjectFileCandidate(path, None, content=b'stores = ["checked"]\n')

    monkeypatch.setattr("environment_store.config.settings.find_project_file", found)

    assert _resolve(tmp_path).stores == ("checked",)


@pytest.mark.parametrize(
    "fields",
    [
        {"stores": ("NOT VALID",)},
        {"key_paths": {"X Y": Path("/k")}},
        {"key_paths": {"a": Path("relative.key")}},
    ],
)
def test_settings_validate_their_invariants(fields: dict[str, object]) -> None:
    valid = Settings(
        connection=None,
        connection_source=None,
        ordered_overwrite=True,
        stores=(),
        key_paths={},
        project_file=None,
        warnings=(),
    )

    with pytest.raises(ValidationError):
        dataclasses.replace(valid, **fields)


# --- password warning --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "connection",
    [
        f"postgresql://user:{_HIDDEN}@host/db",
        f"postgresql://host/db?password={_HIDDEN}",
        f"postgresql://host/db?sslpassword={_HIDDEN}",
        f"postgresql://host/db?pass%77ord={_HIDDEN}",
    ],
)
def test_password_in_the_project_file_connection_is_warned_about(
    tmp_path: Path, connection: str
) -> None:
    path = _project(tmp_path, f'connection = "{connection}"\n')

    settings = _resolve(tmp_path)

    assert len(settings.warnings) == 1
    warning = settings.warnings[0]
    assert str(path) in warning
    assert ENV_CONNECTION in warning
    assert _HIDDEN not in warning


@pytest.mark.parametrize(
    ("connection", "environ"),
    [
        (_OPTION_CONNECTION, {}),
        (None, {ENV_CONNECTION: _ENV_CONNECTION}),
    ],
)
def test_password_warning_is_given_also_when_the_connection_is_overridden(
    tmp_path: Path, connection: str | None, environ: dict[str, str]
) -> None:
    _project(tmp_path, f'connection = "postgresql://u:{_HIDDEN}@host/db"\n')

    settings = _resolve(tmp_path, connection=connection, environ=environ)

    assert len(settings.warnings) == 1
    assert settings.connection_source is not ConnectionSource.PROJECT_FILE


def test_connection_without_password_gives_no_warning(tmp_path: Path) -> None:
    _project(tmp_path, 'connection = "postgresql://user@host/db"\n')

    assert _resolve(tmp_path).warnings == ()


# --- untrusted project file --------------------------------------------------------------------


def test_untrusted_project_file_only_adds_a_warning(tmp_path: Path) -> None:
    path = _project(
        tmp_path,
        f'stores = ["a"]\nordered_overwrite = false\n[keys]\na = "a.key"\n'
        f'connection = "postgresql://u:{_HIDDEN}@host/db"\n',
    )

    settings = _resolve(tmp_path, uid=os.geteuid() + 1)

    assert settings.warnings == (f"ignoring project file '{path}': owned by another user",)
    assert settings.connection is None
    assert settings.stores == ()
    assert dict(settings.key_paths) == {}
    assert settings.ordered_overwrite is True
    assert settings.project_file is None


def test_untrusted_project_file_is_not_parsed(tmp_path: Path) -> None:
    path = _project(tmp_path, "this is not toml")
    path.chmod(0o666)

    settings = _resolve(tmp_path)

    assert settings.warnings == (f"ignoring project file '{path}': writable by every user",)
