from pathlib import Path

import pytest

from environment_store.adapters.files import directory_from_url
from environment_store.core.errors import ValidationError


def test_absolute_url_names_an_absolute_directory() -> None:
    assert directory_from_url("json:///srv/envs", scheme="json") == Path("/srv/envs")


def test_relative_url_is_resolved_against_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert directory_from_url("toml://config/envs", scheme="toml") == tmp_path / "config" / "envs"


def test_tilde_expands_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert directory_from_url("json://~/envs", scheme="json") == tmp_path / "envs"


def test_scheme_is_case_insensitive() -> None:
    assert directory_from_url("JSON:///srv/envs", scheme="json") == Path("/srv/envs")


@pytest.mark.parametrize(
    ("url", "scheme"),
    [
        ("toml:///srv/envs", "json"),
        ("json:///srv/envs", "toml"),
        ("sqlite:///envs.db", "json"),
        ("/srv/envs", "json"),
    ],
)
def test_url_with_another_scheme_is_rejected(url: str, scheme: str) -> None:
    with pytest.raises(ValidationError):
        directory_from_url(url, scheme=scheme)


@pytest.mark.parametrize("url", ["json://", "json://dir\x00x"])
def test_url_without_a_usable_directory_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="directory"):
        directory_from_url(url, scheme="json")


def test_unknown_user_in_tilde_path_is_rejected() -> None:
    with pytest.raises(ValidationError, match="home directory"):
        directory_from_url("json://~no-such-user-for-envstore-tests/envs", scheme="json")
