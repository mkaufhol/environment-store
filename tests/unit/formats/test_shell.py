import json
import subprocess
import sys
from collections.abc import Mapping
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from environment_store.core.errors import ValidationError
from environment_store.formats.shell import posix_exports
from tests.support.strategies import values, variable_names

_SH: Final = "/bin/sh"
_PRINT_ENV: Final = "import json, os; print(json.dumps(dict(os.environ)))"


def _evaluate(script: str, *, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Run `eval` of the statements in /bin/sh, then print the resulting environment as JSON."""
    program = 'eval "$1" || exit 99\nexec "$2" -c "$3"'
    result = subprocess.run(  # noqa: S603 - fixed shell, statements passed as an argument
        [_SH, "-c", program, "sh", script, sys.executable, _PRINT_ENV],
        capture_output=True,
        text=True,
        check=True,
        env=dict(environment or {}),
    )
    loaded: dict[str, str] = json.loads(result.stdout)
    return loaded


# Prefixed so that generated names never hit variables the shell sets or protects itself
# (PWD, SHLVL, PPID, IFS, …); the quoting under test does not depend on the name.
def _test_names() -> st.SearchStrategy[str]:
    return variable_names().map(lambda name: f"T_{name}")


def test_posix_exports_with_overwrite_writes_plain_export_statements() -> None:
    output = posix_exports({"DB_HOST": "localhost", "GREETING": "it's me"}, overwrite=True)

    assert output == "export DB_HOST=localhost\nexport GREETING='it'\"'\"'s me'\n"


def test_posix_exports_without_overwrite_skips_variables_already_set() -> None:
    output = posix_exports({"DB_HOST": "local host"}, overwrite=False)

    assert output == "[ -n \"${DB_HOST+x}\" ] || export DB_HOST='local host'\n"


def test_posix_exports_quotes_empty_values() -> None:
    assert posix_exports({"EMPTY": ""}, overwrite=True) == "export EMPTY=''\n"


def test_posix_exports_of_nothing_is_empty() -> None:
    assert posix_exports({}, overwrite=False) == ""


@pytest.mark.parametrize("name", ["9LIVES__X", "A-B", "", "A B", "A;rm -rf /", "Ä"])
def test_posix_exports_refuses_names_that_are_not_posix_variable_names(name: str) -> None:
    with pytest.raises(ValidationError, match="POSIX") as excinfo:
        posix_exports({name: "v"}, overwrite=True)

    assert repr(name) in str(excinfo.value)


def test_posix_exports_refuses_nul_without_echoing_the_value() -> None:
    with pytest.raises(ValidationError, match="NUL") as excinfo:
        posix_exports({"TOKEN": "sec\x00ret"}, overwrite=True)

    assert "sec" not in str(excinfo.value)


@given(st.dictionaries(_test_names(), values(), max_size=6))
def test_posix_exports_round_trip_exactly_through_bin_sh(variables: dict[str, str]) -> None:
    loaded = _evaluate(posix_exports(variables, overwrite=True))

    assert {name: loaded.get(name) for name in variables} == variables


@given(
    st.dictionaries(_test_names(), values(), max_size=4),
    st.dictionaries(_test_names(), values(), max_size=4),
)
def test_posix_exports_without_overwrite_keep_existing_values_in_bin_sh(
    variables: dict[str, str], existing: dict[str, str]
) -> None:
    loaded = _evaluate(posix_exports(variables, overwrite=False), environment=existing)

    expected = variables | existing
    assert {name: loaded.get(name) for name in expected} == expected


def test_posix_exports_with_overwrite_replace_existing_values_in_bin_sh() -> None:
    loaded = _evaluate(posix_exports({"T_A": "new"}, overwrite=True), environment={"T_A": "old"})

    assert loaded["T_A"] == "new"


def test_posix_exports_keep_an_existing_empty_value_without_overwrite() -> None:
    loaded = _evaluate(posix_exports({"T_A": "new"}, overwrite=False), environment={"T_A": ""})

    assert loaded["T_A"] == ""


def test_eval_of_skipped_statements_succeeds_under_set_e() -> None:
    # `[ -z … ] && export …` would make `eval` return 1 for an already set last variable,
    # which aborts scripts running with `set -e`.
    script = posix_exports({"T_A": "new"}, overwrite=False)
    result = subprocess.run(  # noqa: S603 - fixed shell, statements passed as an argument
        [_SH, "-ec", 'eval "$1"; echo reached', "sh", script],
        capture_output=True,
        text=True,
        check=False,
        env={"T_A": "old"},
    )

    assert (result.returncode, result.stdout) == (0, "reached\n")
