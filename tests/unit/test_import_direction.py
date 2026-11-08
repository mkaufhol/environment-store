"""Import direction between the layers of the package.

core <- crypto <- service; core <- adapters; core <- formats; core, crypto <- config;
core, crypto, service, formats, config <- library; core, config, library, formats <- cli, tui.
Adapter subpackages import core and adapters.sql only, never each other. No frontend layer
imports adapters, service or crypto: the frontends use the library. One exception: the
`envs tui` command module may import `tui`, inside its command function only, so the optional
extra loads only when `envs tui` runs; the TUI never imports the CLI.
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
# Adapters are layered per subpackage: `adapters.<name>`; `adapters` alone is the package root.
ALLOWED_IMPORTS: Final[dict[str, frozenset[str]]] = {
    "core": frozenset({"core"}),
    "crypto": frozenset({"core", "crypto"}),
    "service": frozenset({"core", "crypto", "service"}),
    "adapters": frozenset({"core"}),
    "adapters.sql": frozenset({"core", "adapters.sql"}),
    "adapters.files": frozenset({"core", "adapters.files", "_toml"}),
    "adapters.sqlite": frozenset({"core", "adapters.sql", "adapters.sqlite"}),
    "adapters.postgres": frozenset({"core", "adapters.sql", "adapters.postgres"}),
    "formats": frozenset({"core", "formats", "_toml"}),
    "config": frozenset({"core", "crypto", "config"}),
    "library": frozenset({"core", "crypto", "service", "formats", "config", "library"}),
    "cli": frozenset({"core", "config", "library", "formats", "cli"}),
    "tui": frozenset({"core", "config", "library", "formats", "tui"}),
}

# Module -> extra layers only it may import.
_MODULE_EXCEPTIONS: Final[dict[str, frozenset[str]]] = {
    "environment_store.cli.tui_command": frozenset({"tui"}),
}


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != _PACKAGE or len(parts) < 2:
        return None
    if parts[1] == "adapters" and len(parts) > 2:
        return ".".join(parts[1:3])
    return parts[1]


def _parent_layers(layer: str) -> set[str]:
    parts = layer.split(".")
    return {".".join(parts[:end]) for end in range(1, len(parts))}


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
    if layer not in ALLOWED_IMPORTS:
        return []
    allowed = ALLOWED_IMPORTS[layer] | _MODULE_EXCEPTIONS.get(module, frozenset())
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
        ("environment_store.cli.app", "from environment_store.service import X", 1),
        ("environment_store.cli.app", "from environment_store.crypto import x", 1),
        ("environment_store.cli.app", "import environment_store.adapters.sqlite", 1),
        ("environment_store.cli.app", "from environment_store.tui import run_tui", 1),
        ("environment_store.cli.app", "import environment_store", 1),
        ("environment_store.cli.tui_command", "from environment_store.tui import run_tui", 0),
        ("environment_store.cli.tui_command", "from environment_store.service import X", 1),
        ("environment_store.cli.stores", "import environment_store.tui", 1),
        ("environment_store.tui.app", "from environment_store.library.store import x", 0),
        ("environment_store.tui.app", "from environment_store.config.secrets import x", 0),
        ("environment_store.tui.app", "from environment_store.tui.session import x", 0),
        ("environment_store.tui.app", "from environment_store.cli.app import app", 1),
        ("environment_store.tui.app", "from environment_store.cli import tui_command", 1),
        ("environment_store.tui.app", "from environment_store.service import x", 1),
        ("environment_store.tui.app", "from environment_store.crypto import x", 1),
        ("environment_store.tui.app", "import environment_store.adapters.files", 1),
        ("environment_store.cli.app", "from environment_store.library.store import x", 0),
        ("environment_store.cli.app", "from environment_store.config.settings import x", 0),
        ("environment_store.cli.app", "from environment_store.formats.infer import x", 0),
        ("environment_store.cli.state", "from environment_store.cli.output import x", 0),
        (
            "environment_store.adapters.files",
            "from environment_store.adapters.postgres import o",
            1,
        ),
        ("environment_store.adapters.files", "from environment_store.adapters import sql", 1),
        (
            "environment_store.adapters.sql.codec",
            "from environment_store.adapters.sqlite import x",
            1,
        ),
        ("environment_store.adapters.sql.codec", "from environment_store._toml import dumps", 1),
        ("environment_store.adapters.sqlite", "from environment_store.adapters.sql import x", 0),
        ("environment_store.adapters.postgres.db", "import environment_store.adapters.files", 1),
        ("environment_store.adapters", "from environment_store.adapters.sql import x", 1),
        ("environment_store.formats.dotenv", "from environment_store.adapters.files import x", 1),
        ("environment_store.config.settings", "from environment_store.crypto import x", 0),
        ("environment_store.config.settings", "from environment_store.service import x", 1),
        ("environment_store.config.settings", "from environment_store.library import x", 1),
        ("environment_store.config.secrets", "from environment_store.formats import x", 1),
        ("environment_store.library.store", "from environment_store.service import x", 0),
        ("environment_store.library.store", "from environment_store.config import x", 0),
        ("environment_store.library.store", "from environment_store.formats import x", 0),
        ("environment_store.library.store", "import environment_store.adapters.sqlite", 1),
        ("environment_store.library.store", "from environment_store.adapters import x", 1),
        ("environment_store.library.store", "from environment_store.cli import x", 1),
        ("environment_store.library.store", "import environment_store", 1),
    ],
)
def test_import_direction_checker_detects_upward_imports(
    module: str, source: str, expected: int
) -> None:
    assert len(_violations(module, source)) == expected


@pytest.mark.parametrize(("module", "path"), _source_modules(), ids=str)
def test_module_imports_only_from_lower_layers(module: str, path: Path) -> None:
    assert _violations(module, path.read_text(encoding="utf-8")) == []


def _layer_packages() -> list[tuple[str, frozenset[str]]]:
    """Each restricted layer's top module present in the tree, with the layers it must not load."""
    return [
        (
            module,
            frozenset(ALLOWED_IMPORTS) - ALLOWED_IMPORTS[layer] - {layer} - _parent_layers(layer),
        )
        for module, _ in _source_modules()
        if (layer := _layer(module)) in ALLOWED_IMPORTS and module == f"{_PACKAGE}.{layer}"
    ]


def test_layer_packages_are_found_in_the_source_tree() -> None:
    found = {package for package, _ in _layer_packages()}

    assert {
        "environment_store.core",
        "environment_store.crypto",
        "environment_store.service",
        "environment_store.adapters",
        "environment_store.adapters.sql",
        "environment_store.config",
        "environment_store.library",
        "environment_store.cli",
        "environment_store.tui",
    } <= found


def test_every_package_and_adapter_subpackage_has_import_rules() -> None:
    # An unlisted layer would go unchecked, so a new adapter must get its own entry.
    packages = {
        path.parent.relative_to(_SRC).as_posix().replace("/", ".")
        for pattern in ("*/__init__.py", "adapters/*/__init__.py")
        for path in _SRC.glob(pattern)
    }

    assert packages <= set(ALLOWED_IMPORTS)


def test_adapter_subpackages_may_not_load_each_other() -> None:
    forbidden = dict(_layer_packages())["environment_store.adapters.sql"]

    assert {"adapters.files", "adapters.sqlite", "adapters.postgres", "crypto"} <= forbidden
    assert "adapters" not in forbidden


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [pytest.param(package, forbidden, id=package) for package, forbidden in _layer_packages()],
)
def test_layer_loads_no_higher_layer_in_a_fresh_interpreter(
    package: str, forbidden: frozenset[str]
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


def _modules_importing(layer: str) -> set[str]:
    return {
        module
        for module, path in _source_modules()
        if any(
            _layer(imported) == layer
            for imported in _imported_modules(path.read_text(encoding="utf-8"))
        )
    }


def test_only_the_tui_command_module_of_the_cli_imports_the_tui() -> None:
    cli_modules = {module for module in _modules_importing("tui") if _layer(module) == "cli"}

    assert cli_modules == {"environment_store.cli.tui_command"}


def test_no_tui_module_imports_the_cli() -> None:
    assert {module for module in _modules_importing("cli") if _layer(module) == "tui"} == set()


def test_the_tui_command_imports_the_tui_only_inside_a_function() -> None:
    path = _SRC / "cli" / "tui_command.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level: list[ast.stmt] = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]

    assert all(
        _layer(module) != "tui"
        for module in _imported_modules(ast.unparse(ast.Module(body=top_level, type_ignores=[])))
    )
    assert "environment_store.tui" in _imported_modules(path.read_text(encoding="utf-8"))
