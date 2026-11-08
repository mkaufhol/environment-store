r"""The shell side of completion: the scripts and the answers to them (spec §6.15, D54).

The protocol is click's: the script runs the program with `_<PROG>_COMPLETE=<shell>_complete`
in its environment (`_ENVS_COMPLETE` for `envs`, `_ENVIRONMENT_STORE_COMPLETE` for
`environment-store`), plus `COMP_WORDS` and `COMP_CWORD`; the program prints one candidate per
item with its type (`plain`, or `file` / `dir` for the shell's own path completion) and exits.

typer vendors click without click's bash, zsh and fish classes (it ships its own, which know no
item types), so they are reproduced here on top of the vendored `ShellComplete` base, which
parses the line like the real command does. typer's `--install-completion` stays off: envs
never edits shell configuration files.

Completion is silent (D54): whatever goes wrong while answering, the answer is empty, and
nothing reaches stderr, not even a Python warning.
"""

import contextlib
import io
import os
import re
import warnings
from collections.abc import Mapping, MutableMapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, override

from typer.completion import shell_completion

if TYPE_CHECKING:
    from typer._click import Command

__all__ = ["PASSTHROUGH", "SHELLS", "answer", "complete_var", "program_name", "script"]

PASSTHROUGH: Final = "environment_store.passthrough"
"""The context meta key of the words after a passthrough command's `--` (C4).

Completion offers none of its own candidates once it is set: the words are the command `run`
executes, which the shell completes (§6.13, §6.15).
"""

_PROGRAM: Final = "envs"
# A name a shell can complete; `python -m environment_store.cli` falls back to `envs`.
_PROGRAM_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_COMPLETE: Final = "complete"
# bash splits words at both (COMP_WORDBREAKS). No candidate of envs contains ':' (store and
# variable names cannot), so the reply needs no trimming like `__ltrim_colon_completions`.
_WORD_BREAKS: Final = frozenset({"=", ":"})
_FILE: Final = "file"

# bash >= 4.4 (compopt, complete -o nosort). After `STORE=` the reply keeps no space.
_BASH_SCRIPT: Final = r"""%(complete_func)s() {
    local IFS=$'\n'
    local response

    response=$(env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD=$COMP_CWORD \
%(complete_var)s=bash_complete $1)

    for completion in $response; do
        IFS=',' read type value <<< "$completion"

        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=($value)
            [[ $value == *= ]] && compopt -o nospace
        fi
    done

    return 0
}

%(complete_func)s_setup() {
    complete -o nosort -F %(complete_func)s %(prog_name)s
}

%(complete_func)s_setup;
"""

# A path after `STORE=` (`-k STORE=PATH`) is completed without the `STORE=` prefix. `STORE=`
# itself is added without zsh's space suffix (`-S ''`), like bash's `compopt -o nospace`.
# The response is iterated quoted: the path item of an empty word has an empty value, and an
# unquoted `${response}` would drop it and shift every later triple by one.
_ZSH_SCRIPT: Final = r"""#compdef %(prog_name)s

%(complete_func)s() {
    local -a completions
    local -a completions_without_suffix
    local -a completions_with_descriptions
    local -a response
    (( ! $+commands[%(prog_name)s] )) && return 1

    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) \
%(complete_var)s=zsh_complete %(prog_name)s)}")

    for type key descr in "${response[@]}"; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" && "$key" == *= ]]; then
                completions_without_suffix+=("$key")
            elif [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                completions_with_descriptions+=("$key":"$descr")
            fi
        elif [[ "$type" == "dir" || "$type" == "file" ]]; then
            [[ "$PREFIX" == *=$key ]] && compset -P '*='
            if [[ "$type" == "dir" ]]; then
                _path_files -/
            else
                _path_files -f
            fi
        fi
    done

    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi

    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi

    if [ -n "$completions_without_suffix" ]; then
        compadd -U -S '' -V unsorted -a completions_without_suffix
    fi
}

if [[ $zsh_eval_context[-1] == loadautofunc ]]; then
    # autoload from fpath: only this first call runs here, so bind the command to the
    # completer for every later Tab, then complete now
    compdef %(complete_func)s %(prog_name)s
    %(complete_func)s "$@"
else
    # eval/source/. command, register function for later
    compdef %(complete_func)s %(prog_name)s
fi
"""

# After `-k STORE=` the answer is only the path, but fish matches candidates against the whole
# token: the `STORE=` prefix is put back before each completed path.
_FISH_SCRIPT: Final = r"""function %(complete_func)s;
    set -l token (commandline -t);
    set -l response (env %(complete_var)s=fish_complete COMP_WORDS=(commandline -cp) \
COMP_CWORD=(commandline -t) %(prog_name)s);

    for completion in $response;
        set -l metadata (string split -m 1 "," $completion);

        if test $metadata[1] = "dir";
            __fish_complete_directories $metadata[2];
        else if test $metadata[1] = "file";
            set -l prefix (string match -r -- '^[^=]*=' "$token");
            test "$metadata[2]" = "$token"; and set prefix;
            for path in (__fish_complete_path $metadata[2]);
                echo "$prefix$path";
            end;
        else if test $metadata[1] = "plain";
            echo $metadata[2];
        end;
    end;
end;

complete --no-files --command %(prog_name)s --arguments \
"(%(complete_func)s)";
"""


class _Shell(shell_completion.ShellComplete):
    """What the three shells share: the script variables and the passthrough rule."""

    @override
    def get_completions(
        self, args: list[str], incomplete: str
    ) -> list[shell_completion.CompletionItem]:
        """The candidates of the parameter in question; after `run ... --`, the shell's files."""
        # The vendored click's own steps, with the passthrough check in between.
        ctx = shell_completion._resolve_context(self.cli, self.ctx_args, self.prog_name, args)
        if PASSTHROUGH in ctx.meta:
            return [shell_completion.CompletionItem(incomplete, type=_FILE)]
        obj, incomplete = shell_completion._resolve_incomplete(ctx, args, incomplete)
        return obj.shell_complete(ctx, incomplete)

    @override
    def source_vars(self) -> dict[str, Any]:
        """The script's variables: function name, environment variable, program name."""
        return {
            "complete_func": self.func_name,
            "complete_var": self.complete_var,
            "prog_name": self.prog_name,
        }


class BashComplete(_Shell):
    """bash >= 4.4: `COMP_WORDS` / `COMP_CWORD`, one `type,value` line per item."""

    name: ClassVar[str] = "bash"
    source_template: ClassVar[str] = _BASH_SCRIPT

    @override
    def get_completion_args(self) -> tuple[list[str], str]:
        """The complete words after the program name, and the word being completed."""
        words = shell_completion.split_arg_string(os.environ["COMP_WORDS"])
        cword = int(os.environ["COMP_CWORD"])
        current = words[cword] if cword < len(words) else ""
        typed = _glue_separators([*words[1:cword], current])
        return typed[:-1], typed[-1]

    @override
    def format_completion(self, item: shell_completion.CompletionItem) -> str:
        """`type,value`."""
        return f"{item.type},{item.value}"


class ZshComplete(_Shell):
    """zsh: `COMP_WORDS` / `COMP_CWORD`, three lines per item: type, value, help or `_`."""

    name: ClassVar[str] = "zsh"
    source_template: ClassVar[str] = _ZSH_SCRIPT

    @override
    def get_completion_args(self) -> tuple[list[str], str]:
        """The complete words after the program name, and the word being completed."""
        words = shell_completion.split_arg_string(os.environ["COMP_WORDS"])
        cword = int(os.environ["COMP_CWORD"])
        return words[1:cword], words[cword] if cword < len(words) else ""

    @override
    def format_completion(self, item: shell_completion.CompletionItem) -> str:
        """Type, value and help on three lines; `_describe` needs escaped colons."""
        help_text = item.help or "_"
        value = item.value.replace(":", r"\:") if help_text != "_" else item.value
        return f"{item.type}\n{value}\n{help_text}"


class FishComplete(_Shell):
    """fish: `COMP_WORDS` is the line up to the cursor, `COMP_CWORD` the current token."""

    name: ClassVar[str] = "fish"
    source_template: ClassVar[str] = _FISH_SCRIPT

    @override
    def get_completion_args(self) -> tuple[list[str], str]:
        """The complete words after the program name, and the token being completed."""
        words = shell_completion.split_arg_string(os.environ["COMP_WORDS"])
        token = os.environ["COMP_CWORD"]
        incomplete = shell_completion.split_arg_string(token)[0] if token else ""
        args = words[1:]
        # fish has the token in both variables.
        if incomplete and args and args[-1] == incomplete:
            args.pop()
        return args, incomplete

    @override
    def format_completion(self, item: shell_completion.CompletionItem) -> str:
        """`type,value`, with a tab and the help if there is one."""
        if item.help:
            return f"{item.type},{item.value}\t{' '.join(item.help.split())}"
        return f"{item.type},{item.value}"


SHELLS: Final[Mapping[str, type[_Shell]]] = MappingProxyType(
    {shell.name: shell for shell in (BashComplete, ZshComplete, FishComplete)}
)
"""The supported shells by name."""


def program_name(invoked: str | None) -> str:
    """The program name the script completes: the name envs was run as.

    Args:
        invoked: The root context's name, e.g. `envs` or `environment-store`.

    Returns:
        That name, or `envs` if it is none a shell could complete (e.g. `python -m ...`).
    """
    if invoked is None or not _PROGRAM_NAME.fullmatch(invoked):
        return _PROGRAM
    return invoked


def complete_var(prog_name: str) -> str:
    """The environment variable of the protocol, as click and typer derive it.

    Args:
        prog_name: The program name.

    Returns:
        E.g. `_ENVS_COMPLETE` or `_ENVIRONMENT_STORE_COMPLETE`.
    """
    return f"_{prog_name}_COMPLETE".replace("-", "_").upper()


def script(cli: "Command", shell: str, prog_name: str) -> str:
    """The completion script of a shell for a program name.

    Args:
        cli: The root command.
        shell: `bash`, `zsh` or `fish`.
        prog_name: The program name the script completes.

    Returns:
        The script, ending with a newline.
    """
    return SHELLS[shell](cli, {}, prog_name, complete_var(prog_name)).source()


def answer(
    cli: "Command",
    # Any: click's own type for the context arguments that main() passes through.
    ctx_args: MutableMapping[str, Any],
    prog_name: str,
    instruction: str,
) -> str:
    """Answer one completion request; never raises and never writes to stderr (D54).

    Args:
        cli: The root command.
        ctx_args: The extra context arguments `main()` was given (tests pass `obj`).
        prog_name: The program name.
        instruction: The value of the protocol variable, e.g. `zsh_complete`.

    Returns:
        The candidates in the shell's format; empty for an unknown instruction or on any
        error.
    """
    shell, _, action = instruction.partition("_")
    shell_class = SHELLS.get(shell)
    if shell_class is None or action != _COMPLETE:
        return ""
    # Only the computed answer reaches stdout: zsh reads it in triples, so a stray line (e.g.
    # of a callback) would shift every item.
    with (
        warnings.catch_warnings(),
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        warnings.simplefilter("ignore")
        try:
            return shell_class(cli, ctx_args, prog_name, complete_var(prog_name)).complete()
        # D54: a completion that fails offers nothing instead of a traceback.
        except Exception:  # noqa: BLE001 - any failure means "no candidates"
            return ""


def _glue_separators(words: list[str]) -> list[str]:
    # bash splits words at '=' and ':' (COMP_WORDBREAKS): `-k a=b` arrives as `-k`, `a`, `=`,
    # `b`, and `-c sqlite:///a.db` as `-c`, `sqlite`, `:`, `///a.db` (§6.15: `-c` on the line).
    glued: list[str] = []
    attach = False
    for word in words:
        if word in _WORD_BREAKS and glued:
            glued[-1] += word
            attach = True
        elif attach:
            glued[-1] += word
            attach = False
        else:
            glued.append(word)
    return glued
