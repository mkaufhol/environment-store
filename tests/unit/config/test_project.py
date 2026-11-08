import os
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Final

import pytest

from environment_store.config.project import (
    PROJECT_FILE_NAME,
    ProjectFile,
    ProjectFileCandidate,
    anchor_connection,
    decode_project_file,
    find_project_file,
    parse_project_file,
    read_project_file,
    untrusted_reason,
)
from environment_store.core.errors import ConfigurationError, ValidationError

_UID: Final = os.geteuid()
_HIDDEN: Final = "s3cr3t-value-never-echoed"


def _write(directory: Path, text: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / PROJECT_FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


def _parse(text: str, path: Path = Path("/project/.envstore.toml")) -> ProjectFile:
    return parse_project_file(text, path=path)


# --- discovery ---------------------------------------------------------------------------------


def test_project_file_name_is_envstore_toml() -> None:
    assert PROJECT_FILE_NAME == ".envstore.toml"


def test_file_in_the_start_directory_is_found(tmp_path: Path) -> None:
    path = _write(tmp_path)

    assert find_project_file(tmp_path, boundary=tmp_path) == ProjectFileCandidate(
        path, untrusted_reason=None
    )


def test_file_in_a_parent_directory_is_found(tmp_path: Path) -> None:
    path = _write(tmp_path)
    start = tmp_path / "a" / "b"
    start.mkdir(parents=True)

    candidate = find_project_file(start, boundary=tmp_path)

    assert candidate is not None
    assert candidate.path == path


def test_nearest_file_wins(tmp_path: Path) -> None:
    _write(tmp_path)
    nearest = _write(tmp_path / "sub")

    candidate = find_project_file(tmp_path / "sub", boundary=tmp_path)

    assert candidate is not None
    assert candidate.path == nearest


def test_directory_named_like_the_file_is_skipped(tmp_path: Path) -> None:
    path = _write(tmp_path)
    (tmp_path / "sub" / PROJECT_FILE_NAME).mkdir(parents=True)

    candidate = find_project_file(tmp_path / "sub", boundary=tmp_path)

    assert candidate is not None
    assert candidate.path == path


def test_dangling_symlink_named_like_the_file_is_skipped(tmp_path: Path) -> None:
    path = _write(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / PROJECT_FILE_NAME).symlink_to(tmp_path / "missing")

    candidate = find_project_file(tmp_path / "sub", boundary=tmp_path)

    assert candidate is not None
    assert candidate.path == path


def test_search_stops_after_the_boundary(tmp_path: Path) -> None:
    _write(tmp_path)
    boundary = tmp_path / "inner"
    boundary.mkdir()

    assert find_project_file(boundary, boundary=boundary) is None


def test_no_file_found_returns_none(tmp_path: Path) -> None:
    assert find_project_file(tmp_path, boundary=tmp_path) is None


def test_relative_start_is_resolved_against_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path)
    monkeypatch.chdir(tmp_path)

    candidate = find_project_file(Path(), boundary=tmp_path)

    assert candidate is not None
    assert candidate.path == path


def test_search_without_boundary_walks_up_to_the_root(tmp_path: Path) -> None:
    # Whatever lies above tmp_path, the nearest file is the one in tmp_path.
    path = _write(tmp_path)

    candidate = find_project_file(tmp_path)

    assert candidate is not None
    assert candidate.path == path


# --- trust check -------------------------------------------------------------------------------


def test_file_owned_by_another_user_is_untrusted_and_ends_the_search(tmp_path: Path) -> None:
    _write(tmp_path)
    nearest = _write(tmp_path / "sub")

    candidate = find_project_file(tmp_path / "sub", boundary=tmp_path, uid=_UID + 1)

    assert candidate == ProjectFileCandidate(nearest, untrusted_reason="owned by another user")


def test_world_writable_file_is_untrusted(tmp_path: Path) -> None:
    path = _write(tmp_path)
    path.chmod(0o666)

    candidate = find_project_file(tmp_path, boundary=tmp_path)

    assert candidate == ProjectFileCandidate(path, untrusted_reason="writable by every user")


def test_default_uid_is_the_effective_user(tmp_path: Path) -> None:
    path = _write(tmp_path)

    assert find_project_file(tmp_path, boundary=tmp_path) == ProjectFileCandidate(path, None)


def test_trusted_file_content_is_read_at_discovery(tmp_path: Path) -> None:
    _write(tmp_path, 'stores = ["a"]\n')

    candidate = find_project_file(tmp_path, boundary=tmp_path)

    assert candidate is not None
    assert candidate.content == b'stores = ["a"]\n'


def test_untrusted_file_content_is_not_read(tmp_path: Path) -> None:
    _write(tmp_path, 'stores = ["a"]\n')

    candidate = find_project_file(tmp_path, boundary=tmp_path, uid=_UID + 1)

    assert candidate is not None
    assert candidate.content == b""


def test_own_symlink_to_an_own_file_is_trusted(tmp_path: Path) -> None:
    target = tmp_path / "real.toml"
    target.write_text('stores = ["a"]\n', encoding="utf-8")
    link = tmp_path / PROJECT_FILE_NAME
    link.symlink_to(target)

    candidate = find_project_file(tmp_path, boundary=tmp_path)

    assert candidate == ProjectFileCandidate(link, untrusted_reason=None)
    assert candidate.content == b'stores = ["a"]\n'


def test_symlink_owned_by_another_user_is_untrusted_even_to_a_trusted_file(
    tmp_path: Path,
) -> None:
    # The target is owned by root, so only the link's owner can make it untrusted.
    target = Path("/etc/hosts").resolve()
    if not target.is_file() or target.stat().st_uid != 0 or target.stat().st_mode & 0o002:
        pytest.skip("needs a root-owned file that is not world-writable")
    link = tmp_path / PROJECT_FILE_NAME
    link.symlink_to(target)

    candidate = find_project_file(tmp_path, boundary=tmp_path, uid=_UID + 1)

    assert candidate == ProjectFileCandidate(
        link, untrusted_reason="a symbolic link owned by another user"
    )
    assert candidate.content == b""


def test_trust_is_decided_on_the_file_that_was_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, 'stores = ["a"]\n')
    real_open = os.open

    def swapping_open(name: str, flags: int, mode: int = 0o777) -> int:
        # Between the check and the read, the file becomes writable by every user.
        path.chmod(0o666)
        return real_open(name, flags, mode)

    monkeypatch.setattr(os, "open", swapping_open)

    candidate = find_project_file(tmp_path, boundary=tmp_path)

    assert candidate == ProjectFileCandidate(path, untrusted_reason="writable by every user")
    assert candidate.content == b""


def test_file_replaced_by_a_directory_before_opening_is_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path)
    real_open = os.open

    def swapping_open(name: str, flags: int, mode: int = 0o777) -> int:
        path.unlink()
        path.mkdir()
        return real_open(name, flags, mode)

    monkeypatch.setattr(os, "open", swapping_open)

    candidate = find_project_file(tmp_path, boundary=tmp_path)

    assert candidate == ProjectFileCandidate(path, untrusted_reason="not a regular file")


def test_trusted_file_that_fails_while_being_read_is_a_configuration_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path)

    def failing_fstat(fd: int) -> os.stat_result:
        raise OSError(5, "Input/output error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", failing_fstat)
        with pytest.raises(ConfigurationError, match="cannot read project file") as caught:
            find_project_file(tmp_path, boundary=tmp_path)

    assert "Input/output error" in str(caught.value)


def test_trusted_file_that_cannot_be_opened_is_a_configuration_error(tmp_path: Path) -> None:
    path = _write(tmp_path, 'stores = ["a"]\n')
    path.chmod(0)
    if os.access(path, os.R_OK):  # root can read anyway
        pytest.skip("running as root")

    with pytest.raises(ConfigurationError, match="cannot read project file"):
        find_project_file(tmp_path, boundary=tmp_path)


@pytest.mark.parametrize(
    ("st_uid", "st_mode", "reason"),
    [
        (1000, stat.S_IFREG | 0o644, None),
        (0, stat.S_IFREG | 0o644, None),
        (1000, stat.S_IFREG | 0o664, None),
        (1001, stat.S_IFREG | 0o644, "owned by another user"),
        (1000, stat.S_IFREG | 0o646, "writable by every user"),
        (0, stat.S_IFREG | 0o666, "writable by every user"),
        (1001, stat.S_IFREG | 0o666, "owned by another user"),
    ],
)
def test_untrusted_reason_by_owner_and_mode(st_uid: int, st_mode: int, reason: str | None) -> None:
    assert untrusted_reason(st_uid, st_mode, 1000) == reason


# --- schema ------------------------------------------------------------------------------------


def test_empty_file_has_no_settings() -> None:
    project = _parse("")

    assert project.stores == ()
    assert dict(project.keys) == {}
    assert project.ordered_overwrite is None
    assert project.connection is None
    assert project.path == Path("/project/.envstore.toml")


def test_full_file_is_parsed() -> None:
    project = _parse(
        'stores = ["base_conf", "db-certs"]\n'
        "ordered_overwrite = false\n"
        'connection = "postgresql://host/db"\n'
        "[keys]\n"
        'db-certs = "/keys/dbc.key"\n'
    )

    assert project.stores == ("base_conf", "db-certs")
    assert dict(project.keys) == {"db-certs": Path("/keys/dbc.key")}
    assert project.ordered_overwrite is False
    assert project.connection == "postgresql://host/db"


def test_key_paths_are_relative_to_the_file_directory() -> None:
    project = _parse('[keys]\na = "keys/a.key"\nb = "../b.key"\n')

    assert dict(project.keys) == {
        "a": Path("/project/keys/a.key"),
        "b": Path("/project/../b.key"),
    }


def test_key_paths_expand_the_home_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/someone")

    project = _parse('[keys]\na = "~/.keys/a.key"\n')

    assert project.keys["a"] == Path("/home/someone/.keys/a.key")


def test_key_path_with_an_unknown_user_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match=r"\[keys\]"):
        _parse('[keys]\na = "~no-such-user-hopefully-xyz/a.key"\n')


def test_project_file_is_immutable() -> None:
    project = _parse('stores = ["a"]\n[keys]\na = "a.key"\n')

    assert isinstance(project.keys, MappingProxyType)


def test_repr_hides_the_connection() -> None:
    project = _parse(f'connection = "postgresql://u:{_HIDDEN}@host/db"\n')

    assert _HIDDEN not in repr(project)


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ('store = ["a"]\n', "'store'"),
        ("[stores]\na = 1\n", "'stores'"),
        (f'stores = "{_HIDDEN}"\n', "'stores'"),
        ("stores = [1]\n", "'stores'"),
        (f'stores = ["{_HIDDEN.upper()}"]\n', "'stores'"),
        ('stores = [""]\n', "'stores'"),
        ('stores = ["9lives"]\n', "starting with a letter"),
        (f'keys = "{_HIDDEN}"\n', "[keys]"),
        (f'[keys]\n"{_HIDDEN.upper()}" = "a.key"\n', "[keys]"),
        ("[keys]\na = 1\n", "[keys]"),
        ('[keys]\na = ""\n', "[keys]"),
        (f'[keys]\na = "envstore-key-v1:{_HIDDEN}"\n', "paths only, never key material"),
        (f'ordered_overwrite = "{_HIDDEN}"\n', "'ordered_overwrite'"),
        ("ordered_overwrite = 1\n", "'ordered_overwrite'"),
        ("connection = 1\n", "'connection'"),
        ('connection = ""\n', "'connection'"),
        ('connection = "json://a\\u0000b"\n', "'connection'"),
        ('[keys]\na = "x\\u0000y"\n', "[keys]"),
        (f'stores = ["a"\nconnection = "{_HIDDEN}', "not valid TOML"),
    ],
)
def test_schema_violations_are_configuration_errors_without_values(text: str, names: str) -> None:
    with pytest.raises(ConfigurationError) as caught:
        _parse(text)

    message = str(caught.value)
    assert names in message
    assert "/project/.envstore.toml" in message
    assert _HIDDEN not in message
    assert _HIDDEN.upper() not in message


def test_unknown_key_error_lists_the_allowed_keys() -> None:
    with pytest.raises(ConfigurationError, match="connection, keys, ordered_overwrite, stores"):
        _parse("extra = 1\n")


def test_connection_is_anchored_at_the_file_directory() -> None:
    project = _parse('connection = "json://envs"\n')

    assert project.connection == "json:///project/envs"


@pytest.mark.parametrize(
    "fields",
    [
        {"path": Path("relative/.envstore.toml")},
        {"stores": ("NOT VALID",)},
        {"keys": {"X Y": Path("/k")}},
        {"keys": {"a": Path("relative.key")}},
    ],
)
def test_project_file_validates_its_invariants(fields: dict[str, object]) -> None:
    arguments: dict[str, object] = {"path": Path("/project/.envstore.toml"), **fields}

    with pytest.raises(ValidationError):
        ProjectFile(**arguments)  # ty: ignore[invalid-argument-type] - built from a table


# --- reading -----------------------------------------------------------------------------------


def test_read_project_file_parses_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, 'stores = ["a"]\n')

    project = read_project_file(path)

    assert project.stores == ("a",)
    assert project.path == path


def test_read_project_file_makes_the_path_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, '[keys]\na = "a.key"\n')
    monkeypatch.chdir(tmp_path)

    project = read_project_file(Path(PROJECT_FILE_NAME))

    assert project.path == tmp_path / PROJECT_FILE_NAME
    assert project.keys["a"] == tmp_path / "a.key"


def test_missing_project_file_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / PROJECT_FILE_NAME

    with pytest.raises(ConfigurationError, match="cannot read project file"):
        read_project_file(path)


def test_unreadable_project_file_is_a_configuration_error(tmp_path: Path) -> None:
    path = _write(tmp_path, 'stores = ["a"]\n')
    path.chmod(0)
    if os.access(path, os.R_OK):  # root can read anyway
        pytest.skip("running as root")

    with pytest.raises(ConfigurationError, match=str(path)):
        read_project_file(path)


def test_decode_project_file_parses_bytes() -> None:
    path = Path("/project/.envstore.toml")

    assert decode_project_file(b'stores = ["a"]\n', path=path).stores == ("a",)


def test_project_file_that_is_not_utf8_is_a_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / PROJECT_FILE_NAME
    path.write_bytes(b'stores = ["\xff"]\n')

    with pytest.raises(ConfigurationError, match="not valid UTF-8"):
        read_project_file(path)


# --- anchor_connection -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "anchored"),
    [
        ("json://envs", "json:///base/envs"),
        ("json://./envs", "json:///base/envs"),
        ("toml://a/b", "toml:///base/a/b"),
        ("JSON://envs", "JSON:///base/envs"),
        ("json:///abs/envs", "json:///abs/envs"),
        ("json://~/envs", "json://~/envs"),
        ("toml://~", "toml://~"),
        ("sqlite:///envs.db", "sqlite:////base/envs.db"),
        ("sqlite:///data/envs.db", "sqlite:////base/data/envs.db"),
        ("SQLite:///envs.db", "SQLite:////base/envs.db"),
        ("sqlite:////abs/envs.db", "sqlite:////abs/envs.db"),
        ("sqlite:///~/envs.db", "sqlite:///~/envs.db"),
        ("postgresql://user@host/db", "postgresql://user@host/db"),
        ("postgres://host/relative", "postgres://host/relative"),
        ("json://", "json://"),
        ("sqlite://", "sqlite://"),
        ("sqlite://host/envs.db", "sqlite://host/envs.db"),
        ("not a url", "not a url"),
    ],
)
def test_anchor_connection_makes_relative_file_paths_absolute(url: str, anchored: str) -> None:
    assert anchor_connection(url, Path("/base")) == anchored
