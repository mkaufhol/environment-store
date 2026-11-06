from importlib import import_module

from environment_store import crypto


def test_crypto_reexports_the_public_names_of_its_modules() -> None:
    modules = [
        import_module(f"environment_store.crypto.{name}") for name in ("aead", "kdf", "keyfile")
    ]
    expected = {name: getattr(module, name) for module in modules for name in module.__all__}

    assert set(crypto.__all__) == set(expected)
    for name, value in expected.items():
        assert getattr(crypto, name) is value
