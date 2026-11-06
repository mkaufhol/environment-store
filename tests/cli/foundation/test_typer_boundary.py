"""No runtime import of `click` or typer's private vendored `typer._click` (plan §6.3)."""

import ast
from pathlib import Path

import environment_store

_SOURCE = Path(environment_store.__file__).parent
_FORBIDDEN = ("click", "typer._click")


def _is_type_checking_block(node: ast.AST) -> bool:
    return isinstance(node, ast.If) and (
        (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
        or (isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING")
    )


def _forbidden(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in _FORBIDDEN)


def _runtime_imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if _is_type_checking_block(node):
            continue
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append(node.module)
        pending.extend(ast.iter_child_nodes(node))
    return found


def test_no_module_imports_click_or_typer_private_click_at_runtime() -> None:
    offenders = [
        f"{path.relative_to(_SOURCE)}: {module}"
        for path in sorted(_SOURCE.rglob("*.py"))
        for module in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if _forbidden(module)
    ]

    assert offenders == []


def test_the_scan_sees_runtime_imports_and_skips_type_checking_blocks() -> None:
    source = (
        "import click\n"
        "from typer._click.exceptions import X\n"
        "import typing\n"
        "if TYPE_CHECKING:\n"
        "    from typer._click import Context\n"
        "if typing.TYPE_CHECKING:\n"
        "    import click.core\n"
        "if other:\n"
        "    from . import sibling\n"
    )

    modules = _runtime_imports(ast.parse(source))

    assert sorted(module for module in modules if _forbidden(module)) == [
        "click",
        "typer._click.exceptions",
    ]
    assert not _forbidden("clicker")
