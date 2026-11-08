"""Private directories of the file-based backends, for JSON/TOML and for SQLite.

Both adapter subpackages carry the same helper, as they may not import each other.
"""

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from environment_store.adapters.files import directories as files_directories
from environment_store.adapters.sqlite import directories as sqlite_directories

type MakeDirectory = Callable[[Path], None]


@pytest.fixture(
    params=[
        pytest.param(files_directories.make_private_directory, id="files"),
        pytest.param(sqlite_directories.make_private_directory, id="sqlite"),
    ]
)
def make_private_directory(request: pytest.FixtureRequest) -> MakeDirectory:
    return request.param


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture(params=[0o022, 0o077, 0o277], ids=["umask-022", "umask-077", "umask-277"])
def umask(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[int]:
    # Depends on tmp_path, so that pytest creates it before the umask changes.
    del tmp_path
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


@pytest.mark.usefixtures("umask")
def test_missing_directory_and_its_parents_are_created_with_mode_0700(
    tmp_path: Path, make_private_directory: MakeDirectory
) -> None:
    directory = tmp_path / "a" / "b" / "c"

    make_private_directory(directory)

    assert [_mode(path) for path in (directory.parent.parent, directory.parent, directory)] == [
        0o700
    ] * 3


@pytest.mark.usefixtures("umask")
def test_existing_directories_keep_their_mode(
    tmp_path: Path, make_private_directory: MakeDirectory
) -> None:
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o755)
    existing = tmp_path / "existing"
    existing.mkdir()
    existing.chmod(0o750)

    make_private_directory(parent / "new")
    make_private_directory(existing)

    assert (_mode(parent), _mode(parent / "new"), _mode(existing)) == (0o755, 0o700, 0o750)


def test_directory_created_concurrently_is_used_and_keeps_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_private_directory: MakeDirectory
) -> None:
    directory = tmp_path / "racing"
    directory.mkdir()
    directory.chmod(0o750)
    # Another process creates it between the existence check and mkdir.
    monkeypatch.setattr(
        Path, "exists", lambda path, **_: path != directory and os.access(path, os.F_OK)
    )

    make_private_directory(directory / "child")

    assert (_mode(directory), _mode(directory / "child")) == (0o750, 0o700)
