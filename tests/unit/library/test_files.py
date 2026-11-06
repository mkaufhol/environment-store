import errno
import os
import stat
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import BackendError, ValidationError
from environment_store.library.files import read_input_file, write_output_file


def _leftovers(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def test_new_file_is_created_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / ".env"

    write_output_file(path, "A=1\n", force=False)

    assert path.read_text(encoding="utf-8") == "A=1\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_text_is_written_as_utf8_without_newline_translation(tmp_path: Path) -> None:
    path = tmp_path / "out.json"

    write_output_file(path, "ä\r\nb\n", force=False)

    assert path.read_bytes() == "ä\r\nb\n".encode()


def test_existing_file_is_refused_without_force(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("keep", encoding="utf-8")

    with pytest.raises(ValidationError, match="already exists") as caught:
        write_output_file(path, "A=1\n", force=False)

    assert str(path) in str(caught.value)
    assert path.read_text(encoding="utf-8") == "keep"


def test_existing_file_is_replaced_atomically_with_force(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("old", encoding="utf-8")
    path.chmod(0o644)

    write_output_file(path, "A=1\n", force=True)

    assert path.read_text(encoding="utf-8") == "A=1\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert _leftovers(tmp_path) == [".env"]


def test_force_creates_a_missing_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"

    write_output_file(path, "A=1\n", force=True)

    assert path.read_text(encoding="utf-8") == "A=1\n"


@pytest.mark.parametrize("force", [False, True])
def test_missing_directory_is_a_backend_error(
    tmp_path: Path,
    force: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    path = tmp_path / "missing" / ".env"

    with pytest.raises(BackendError, match="cannot write") as caught:
        write_output_file(path, "A=1\n", force=force)

    assert str(path) in str(caught.value)


@pytest.mark.parametrize("force", [False, True])
def test_read_only_directory_is_a_backend_error(
    tmp_path: Path,
    force: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    directory = tmp_path / "ro"
    directory.mkdir()
    directory.chmod(0o500)
    if os.access(directory, os.W_OK):  # root ignores the mode
        pytest.skip("running as root")

    try:
        with pytest.raises(BackendError, match="cannot write"):
            write_output_file(directory / ".env", "A=1\n", force=force)
    finally:
        directory.chmod(0o700)
    assert _leftovers(directory) == []


def test_directory_target_with_force_is_a_backend_error_and_leaves_no_temp_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out"
    target.mkdir()

    with pytest.raises(BackendError, match="cannot write") as caught:
        write_output_file(target, "A=1\n", force=True)

    assert str(target) in str(caught.value)
    assert _leftovers(tmp_path) == ["out"]


def test_directory_target_without_force_is_refused_as_existing(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="already exists"):
        write_output_file(tmp_path, "A=1\n", force=False)


def test_failed_replace_removes_the_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_replace(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "replace", failing_replace)
    path = tmp_path / ".env"

    with pytest.raises(BackendError, match="Invalid cross-device link"):
        write_output_file(path, "SECRET=1\n", force=True)

    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("force", [False, True])
def test_failed_write_removes_the_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    def failing_fsync(fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    path = tmp_path / ".env"

    with pytest.raises(BackendError, match="No space left on device"):
        write_output_file(path, "SECRET=1\n", force=force)

    assert _leftovers(tmp_path) == []


@given(text=st.text())
def test_written_text_reads_back_exactly(text: str) -> None:
    # Hypothesis forbids function-scoped fixtures such as tmp_path.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "out"
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            return
        write_output_file(path, text, force=False)

        assert read_input_file(path) == text


# --- read_input_file ---------------------------------------------------------------------------


def test_read_input_file_keeps_crlf_exactly(tmp_path: Path) -> None:
    path = tmp_path / "in.env"
    path.write_bytes(b"A=1\r\nB=2\r\n")

    assert read_input_file(path) == "A=1\r\nB=2\r\n"


def test_read_input_file_missing_is_a_backend_error(tmp_path: Path) -> None:
    path = tmp_path / "missing.env"

    with pytest.raises(BackendError, match="cannot read") as caught:
        read_input_file(path)

    assert str(path) in str(caught.value)


def test_read_input_file_directory_is_a_backend_error(tmp_path: Path) -> None:
    with pytest.raises(BackendError, match="cannot read"):
        read_input_file(tmp_path)


def test_read_input_file_not_utf8_is_a_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "in.env"
    path.write_bytes(b"A=\xff\n")

    with pytest.raises(ValidationError, match="not valid UTF-8") as caught:
        read_input_file(path)

    assert str(path) in str(caught.value)
    assert caught.value.__cause__ is None


# --- paths the OS refuses ----------------------------------------------------------------------


@pytest.mark.parametrize("force", [False, True])
def test_output_path_with_a_nul_character_is_a_validation_error(
    tmp_path: Path,
    force: bool,  # noqa: FBT001 - parametrised table column
) -> None:
    with pytest.raises(ValidationError, match="NUL"):
        write_output_file(tmp_path / "out\0.env", "A=1\n", force=force)
    assert list(tmp_path.iterdir()) == []


def test_input_path_with_a_nul_character_is_a_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="NUL"):
        read_input_file(tmp_path / "in\0.env")
