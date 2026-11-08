import subprocess
import sys
from pathlib import Path
from typing import Final

_PACKAGE: Final = Path(__file__).parent
_SERVERLESS: Final = frozenset({"test_url.py", "test_markers.py"})


def _collected(*arguments: str) -> set[str]:
    result = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=_PACKAGE.parents[2],
    )
    return {line.split("::")[0] for line in result.stdout.splitlines() if "::" in line}


def test_every_server_backed_module_carries_the_postgres_marker() -> None:
    package = str(_PACKAGE.relative_to(_PACKAGE.parents[2]))

    unmarked = _collected(package, "-m", "not postgres")
    marked = _collected(package, "-m", "postgres")

    assert {Path(path).name for path in unmarked} == _SERVERLESS
    assert {Path(path).name for path in marked} == {
        "test_adapter.py",
        "test_contract.py",
        "test_read_only.py",
        "test_security.py",
        "test_setup.py",
    }
