"""Fixtures of every CLI test; the harness itself is documented in `tests/support/cli.py`."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from environment_store.config.settings import ENV_CONNECTION, ENV_ORDERED_OVERWRITE
from tests.support.cli import SCHEMES, CliHarness, Scheme, cli_harness


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ENV_STORE_* variable leaks in, and the working directory is the test's own."""
    monkeypatch.delenv(ENV_CONNECTION, raising=False)
    monkeypatch.delenv(ENV_ORDERED_OVERWRITE, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(params=SCHEMES)
def cli(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[CliHarness]:
    """A harness on a json, a toml and a sqlite backend in turn."""
    scheme: Scheme = request.param
    with cli_harness(tmp_path, scheme) as harness:
        yield harness


@pytest.fixture
def cli_json(tmp_path: Path) -> Iterator[CliHarness]:
    """A harness on a json backend, for tests where the backend does not matter."""
    with cli_harness(tmp_path, "json") as harness:
        yield harness
