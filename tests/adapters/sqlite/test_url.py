from pathlib import Path

import pytest

from environment_store.adapters.sqlite import parse_sqlite_url
from environment_store.core.errors import ValidationError


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///envs.db", Path("envs.db")),
        ("sqlite:///data/envs.db", Path("data/envs.db")),
        ("sqlite:////var/lib/envs.db", Path("/var/lib/envs.db")),
        ("SQLite:///envs.db", Path("envs.db")),
        ("sqlite:///my%20envs.db", Path("my%20envs.db")),
    ],
)
def test_url_maps_three_slashes_to_relative_and_four_to_absolute_paths(
    url: str, expected: Path
) -> None:
    assert parse_sqlite_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "sqlite://",
        "sqlite:///",
        "sqlite:////",
        "sqlite://host/envs.db",
        "sqlite://envs.db",
        "sqlite:///envs.db?mode=ro",
        "sqlite:///envs.db#part",
        "sqlite:///envs\x00.db",
        "json:///envs.db",
        "envs.db",
    ],
)
def test_url_without_a_file_path_or_with_extras_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match=r"sqlite:///"):
        parse_sqlite_url(url)


def test_leading_tilde_expands_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same path rules as json:// and toml://.
    monkeypatch.setenv("HOME", str(tmp_path))

    assert parse_sqlite_url("sqlite:///~/envs/envs.db") == tmp_path / "envs" / "envs.db"


def test_tilde_of_an_unknown_user_is_rejected() -> None:
    with pytest.raises(ValidationError, match="home directory"):
        parse_sqlite_url("sqlite:///~no-such-user-for-envstore-tests/envs.db")
