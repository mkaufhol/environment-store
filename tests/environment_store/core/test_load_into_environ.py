import pytest

from environment_store.adapters.json import JsonFileAdapter
from environment_store.core.manager import EnvironmentStoreManager


@pytest.fixture
def manager(tmp_path):
    manager = EnvironmentStoreManager(adapter=JsonFileAdapter(str(tmp_path / "store.json")))
    manager.set_variables({"A": "root", "B": "root"})
    manager.set_variable("A", "acme", organisation="acme")
    return manager


def test_loads_resolved_variables(manager):
    environ: dict[str, str] = {}
    loaded = manager.load_into_environ(organisation="acme", environ=environ)
    assert environ == {"A": "acme", "B": "root"}
    assert loaded == environ


def test_keeps_existing_values_by_default(manager):
    environ = {"A": "mine"}
    loaded = manager.load_into_environ(organisation="acme", environ=environ)
    assert environ == {"A": "mine", "B": "root"}
    assert loaded == {"B": "root"}


def test_override_replaces_existing_values(manager):
    environ = {"A": "mine"}
    manager.load_into_environ(organisation="acme", override=True, environ=environ)
    assert environ == {"A": "acme", "B": "root"}


def test_defaults_to_os_environ(manager, monkeypatch):
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    manager.load_into_environ(organisation="acme")
    import os

    assert os.environ["A"] == "acme"
    monkeypatch.delenv("A")
    monkeypatch.delenv("B")
