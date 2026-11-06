from environment_store import core
from environment_store.core import clock, errors, models, secrets, validation


def test_core_reexports_the_public_names_of_its_modules() -> None:
    modules = (clock, errors, models, secrets, validation)
    expected = {name: getattr(module, name) for module in modules for name in module.__all__}

    assert set(core.__all__) == set(expected)
    for name, value in expected.items():
        assert getattr(core, name) is value
