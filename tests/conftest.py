import os

import pytest
from hypothesis import settings

# Adapter tests touch disks and databases, so per-example deadlines would only cause flakiness.
settings.register_profile("default", deadline=None)
# CI runs a fixed, reproducible set of examples.
settings.register_profile("ci", deadline=None, max_examples=200, derandomize=True, database=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(autouse=True)
def _no_key_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key of the developer's shell leaks into a test: `ENV_STORE_KEY_*`, `ENV_STORE_LOAD`."""
    for name in list(os.environ):
        if name.startswith("ENV_STORE_KEY_"):
            monkeypatch.delenv(name)
    monkeypatch.delenv("ENV_STORE_LOAD", raising=False)
