"""POSIX shell statements for `export-shell` (spec §6.12, D23).

The output is meant for `eval "$(envs export-shell …)"` in bash, zsh, dash and other POSIX
shells. Values are quoted with `shlex.quote`, so the shell reads them back exactly.
"""

import shlex
from collections.abc import Mapping

from environment_store.core.errors import ValidationError
from environment_store.core.validation import VARIABLE_NAME_PATTERN, validate_value

__all__ = ["posix_exports"]


def posix_exports(variables: Mapping[str, str], *, overwrite: bool) -> str:
    """Build shell statements that export variables.

    Without `overwrite`, each statement is `[ -n "${NAME+x}" ] || export NAME=…`: a variable
    that is already set (even to the empty string) is kept. This is the spec's
    `[ -z … ] && export …` with the test inverted, so that a skipped last statement does not
    make `eval` fail and abort scripts running with `set -e`.

    Args:
        variables: Variable names and values, in output order.
        overwrite: Replace variables that are already set in the shell.

    Returns:
        One statement per line, each ending with a newline; empty for no variables.

    Raises:
        ValidationError: A name is not a POSIX variable name or a value contains NUL. Values
            are never echoed.
    """
    lines: list[str] = []
    for name, value in variables.items():
        _check_name(name)
        validate_value(value, variable=name)
        statement = f"export {name}={shlex.quote(value)}"
        if not overwrite:
            statement = f'[ -n "${{{name}+x}}" ] || {statement}'
        lines.append(f"{statement}\n")
    return "".join(lines)


def _check_name(name: str) -> None:
    # The name is interpolated into shell code unquoted, so it must be a plain identifier.
    if not VARIABLE_NAME_PATTERN.fullmatch(name):
        message = (
            f"{name!r} is not a POSIX shell variable name ({VARIABLE_NAME_PATTERN.pattern}), "
            "so it cannot be exported to a shell"
        )
        raise ValidationError(message)
