import pkgutil
import subprocess
import sys
from importlib import import_module
from importlib.resources import files
from typing import Final

import pytest

import environment_store
from environment_store.core import errors

# Where each public name is defined (spec §7.3, IMPLEMENTATION-PLAN.md §6 L1).
_PUBLIC: Final[dict[str, str]] = {
    "EnvironmentStore": "environment_store.library.store",
    "Environment": "environment_store.library.environment",
    "Source": "environment_store.library.sources",
    "KeyInput": "environment_store.library.sources",
    "load": "environment_store.library.oneliner",
    "generate_key_file": "environment_store.library.keys",
    "generate_key_text": "environment_store.library.keys",
    "parse_key_text": "environment_store.library.keys",
    "CredentialsInProjectFileWarning": "environment_store.config.settings",
    "KeyMaterial": "environment_store.core.secrets",
    "Passphrase": "environment_store.core.secrets",
    "Secret": "environment_store.core.secrets",
    "StoreInfo": "environment_store.core.models",
    "KeyMode": "environment_store.core.models",
    "MergeOrder": "environment_store.core.merge",
    "Format": "environment_store.formats.infer",
    "SetupMode": "environment_store.core.adapter",
    "MigrationReport": "environment_store.core.adapter",
    **dict.fromkeys(errors.__all__, "environment_store.core.errors"),
}


def _all_modules() -> list[str]:
    prefix = f"{environment_store.__name__}."
    walked = pkgutil.walk_packages(environment_store.__path__, prefix)
    return [environment_store.__name__, *sorted(module.name for module in walked)]


def test_package_ships_py_typed_marker() -> None:
    assert files(environment_store).joinpath("py.typed").is_file()


@pytest.mark.parametrize("module", _all_modules())
def test_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    # Importing each module first, alone, catches import cycles that a shared test process hides.
    result = subprocess.run(  # noqa: S603 - fixed interpreter, module names come from pkgutil
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_public_api_is_exactly_the_planned_names() -> None:
    assert set(environment_store.__all__) == {"__version__", *_PUBLIC}


@pytest.mark.parametrize(("name", "module"), sorted(_PUBLIC.items()))
def test_public_name_resolves_to_its_definition(name: str, module: str) -> None:
    assert getattr(environment_store, name) is getattr(import_module(module), name)


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no_such_name"):
        _ = environment_store.no_such_name


def test_dir_lists_the_public_api() -> None:
    assert set(environment_store.__all__) <= set(dir(environment_store))


def test_importing_the_package_loads_neither_library_nor_config() -> None:
    code = (
        "import sys, environment_store\n"
        "print(' '.join(name for name in sys.modules if name.startswith('environment_store.')))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    loaded = result.stdout.split()
    assert not [name for name in loaded if name.split(".")[1] in {"library", "config", "service"}]


def test_public_names_load_lazily_in_a_fresh_interpreter() -> None:
    code = (
        "import sys, environment_store\n"
        "environment_store.load\n"
        "print('environment_store.library.oneliner' in sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "True"
