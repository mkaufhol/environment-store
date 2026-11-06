from importlib import import_module

from environment_store.adapters import sql


def test_sql_reexports_the_public_names_of_its_modules() -> None:
    modules = [
        import_module(f"environment_store.adapters.sql.{name}")
        for name in ("codec", "migrations", "schema", "setup")
    ]
    expected = {name: getattr(module, name) for module in modules for name in module.__all__}

    assert set(sql.__all__) == set(expected)
    for name, value in expected.items():
        assert getattr(sql, name) is value
