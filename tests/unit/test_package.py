import pkgutil
import subprocess
import sys
from importlib.resources import files

import pytest

import environment_store


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
