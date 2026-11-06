from importlib import import_module

from environment_store.adapters import files


def test_files_reexports_the_public_names_of_its_modules() -> None:
    modules = [
        import_module(f"environment_store.adapters.files.{name}")
        for name in ("adapter", "layout", "locking", "serializers", "url")
    ]
    expected = {name: getattr(module, name) for module in modules for name in module.__all__}

    assert set(files.__all__) == set(expected)
    for name, value in expected.items():
        assert getattr(files, name) is value
