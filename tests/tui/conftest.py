"""Fixtures of the TUI tests: a json backend through the library, and the CLI harness."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from environment_store.config.settings import ENV_CONNECTION, ENV_ORDERED_OVERWRITE
from environment_store.library.store import EnvironmentStore
from tests.support.cli import CliHarness, cli_harness, connection_for
from tests.support.kdf import CheapKdf


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ENV_STORE_* variable leaks in, and the working directory is the test's own."""
    monkeypatch.delenv(ENV_CONNECTION, raising=False)
    monkeypatch.delenv(ENV_ORDERED_OVERWRITE, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def cli_json(tmp_path: Path) -> Iterator[CliHarness]:
    """The CLI harness on a json backend, for `envs tui`."""
    with cli_harness(tmp_path, "json") as harness:
        yield harness


@pytest.fixture
def connection(tmp_path: Path) -> str:
    """The connection string of a fresh json backend."""
    return connection_for(tmp_path, "json")


@pytest.fixture
def store(connection: str) -> Iterator[EnvironmentStore]:
    """The store the TUI under test works on (cheap KDF for passphrase stores)."""
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf()) as opened:
        yield opened


@pytest.fixture
def other(connection: str) -> Iterator[EnvironmentStore]:
    """A second library store on the same backend, for concurrent changes."""
    with EnvironmentStore(connection, kdf_params_factory=CheapKdf()) as opened:
        yield opened
