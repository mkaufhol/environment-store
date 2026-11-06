from importlib import import_module
from types import ModuleType
from typing import Final

from environment_store import core

# Loaded by path: `core.merge` is the re-exported function, which shadows the submodule attribute.
_MODULES: Final[tuple[ModuleType, ...]] = tuple(
    import_module(f"environment_store.core.{name}")
    for name in ("clock", "errors", "merge", "models", "secrets", "validation")
)


def test_core_reexports_the_public_names_of_its_modules() -> None:
    expected = {name: getattr(module, name) for module in _MODULES for name in module.__all__}

    assert set(core.__all__) == set(expected)
    for name, value in expected.items():
        assert getattr(core, name) is value
