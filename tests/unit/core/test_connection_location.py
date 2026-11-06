"""Where a connection string points, for messages such as ls-store's `no stores in` (D42, D43)."""

from pathlib import Path

import pytest

from environment_store.core.connection import connection_location

_HOME_URLS = [("json://~/envs", "envs"), ("toml://~/envs", "envs"), ("sqlite:///~/e.db", "e.db")]


@pytest.mark.parametrize("scheme", ["json", "toml"])
def test_relative_file_directory_is_resolved_against_the_working_directory(
    scheme: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert connection_location(f"{scheme}://envs/dev") == str(Path.cwd() / "envs" / "dev")


def test_absolute_file_directory_is_kept(tmp_path: Path) -> None:
    assert connection_location(f"json://{tmp_path / 'envs'}") == str(tmp_path / "envs")


def test_relative_sqlite_file_is_resolved_against_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert connection_location("sqlite:///data/envs.db") == str(Path.cwd() / "data" / "envs.db")


def test_absolute_sqlite_file_is_kept(tmp_path: Path) -> None:
    assert connection_location(f"sqlite:///{tmp_path / 'envs.db'}") == str(tmp_path / "envs.db")


@pytest.mark.parametrize(("url", "name"), _HOME_URLS)
def test_a_leading_tilde_is_expanded(
    url: str, name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert connection_location(url) == str(tmp_path / name)


def test_sqlite_path_of_an_unknown_user_stays_unexpanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    location = connection_location("sqlite:///~no_such_user_d42/e.db")

    assert location == str(Path.cwd() / "~no_such_user_d42" / "e.db")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql://alice:hunter2@db.example:5433/envs",
            "schema 'environment_store' of database 'envs' on host 'db.example:5433'",
        ),
        (
            "postgres://db.example/envs?schema=team_a&password=hunter2",
            "schema 'team_a' of database 'envs' on host 'db.example'",
        ),
        (
            "postgresql://alice@h1:5432,h2:5433/envs",
            "schema 'environment_store' of database 'envs' on host 'h1:5432,h2:5433'",
        ),
        (
            "postgresql:///envs?host=/var/run/postgresql&port=5433",
            "schema 'environment_store' of database 'envs' on host '/var/run/postgresql:5433'",
        ),
        (
            "postgresql://h:5432/db?port=6",
            "schema 'environment_store' of database 'db' on host 'h:6'",
        ),
        (
            "postgresql://[::1]:5432,[::2]/db?port=6",
            "schema 'environment_store' of database 'db' on host '[::1]:6,[::2]:6'",
        ),
        (
            "postgresql://h1:5432,h2/db?port=6,7",
            "schema 'environment_store' of database 'db' on host 'h1:6,h2:7'",
        ),
        (
            "postgresql://h1,h2,h3/db?port=6,7",
            "schema 'environment_store' of database 'db' on host 'h1,h2,h3:6,7'",
        ),
        (
            "postgresql://h:5432/db?host=::1&port=6",
            "schema 'environment_store' of database 'db' on host '::1:6'",
        ),
        (
            "postgresql://",
            "schema 'environment_store' of the default database on the default host",
        ),
    ],
)
def test_postgresql_location_names_host_database_and_schema_without_credentials(
    url: str, expected: str
) -> None:
    location = connection_location(url)

    assert location == expected
    assert "hunter2" not in location
    assert "alice" not in location


def test_an_unknown_scheme_names_only_the_scheme() -> None:
    assert connection_location("memory://anything") == "the memory:// backend"
