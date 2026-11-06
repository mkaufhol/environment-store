"""Import direction (IMPLEMENTATION-PLAN.md §3).

core <- crypto <- service; core <- adapters; core <- formats.
"""

import ast
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

import environment_store

_PACKAGE: Final = "environment_store"
_SRC: Final = Path(environment_store.__file__).parent

# Layer -> the layers it may import from. Layers not listed here are not restricted yet.
_ALLOWED: Final[dict[str, frozenset[str]]] = {
    "core": frozenset({"core"}),
    "crypto": frozenset({"core", "crypto"}),
    "service": frozenset({"core", "crypto", "service"}),
    "adapters": frozenset({"core", "adapters", "_toml"}),
    "formats": frozenset({"core", "formats", "_toml"}),
}


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != _PACKAGE or len(parts) < 2:
        return None
    return parts[1]


def _imported_modules(source: str) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def _violations(module: str, source: str) -> list[str]:
    layer = _layer(module)
    if layer not in _ALLOWED:
        return []
    allowed = _ALLOWED[layer]
    return [
        imported
        for imported in _imported_modules(source)
        if imported == _PACKAGE or (_layer(imported) not in (None, *allowed))
    ]


def _source_modules() -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in sorted(_SRC.rglob("*.py")):
        parts = path.relative_to(_SRC).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found.append((".".join((_PACKAGE, *parts)), path))
    return found


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        ("environment_store.core.models", "from environment_store.crypto import seal", 1),
        ("environment_store.core.models", "import environment_store.service", 1),
        ("environment_store.core.models", "from environment_store import crypto", 1),
        ("environment_store.crypto.aead", "from environment_store.service import X", 1),
        ("environment_store.crypto.aead", "from environment_store.core.models import X", 0),
        ("environment_store.adapters.files", "from environment_store.crypto import seal", 1),
        ("environment_store.adapters.files", "from environment_store._toml import dumps", 0),
        ("environment_store.service", "from environment_store.crypto import seal", 0),
        ("environment_store.service", "import json\nfrom typing import Final", 0),
        ("environment_store.cli.app", "from environment_store.service import X", 0),
    ],
)
def test_import_direction_checker_detects_upward_imports(
    module: str, source: str, expected: int
) -> None:
    assert len(_violations(module, source)) == expected


@pytest.mark.parametrize(("module", "path"), _source_modules(), ids=str)
def test_module_imports_only_from_lower_layers(module: str, path: Path) -> None:
    assert _violations(module, path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("environment_store.core", ("crypto", "service", "adapters", "formats")),
        ("environment_store.crypto", ("service", "adapters", "formats")),
        ("environment_store.service", ("adapters", "formats")),
    ],
)
def test_layer_loads_no_higher_layer_in_a_fresh_interpreter(
    package: str, forbidden: tuple[str, ...]
) -> None:
    code = (
        f"import sys, {package}\n"
        f"print('\\n'.join(name for name in sys.modules if name.startswith('{_PACKAGE}.')))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    loaded = {_layer(name) for name in result.stdout.split()}
    assert loaded.isdisjoint(forbidden)
