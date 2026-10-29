"""Command line interface for the EnvironmentStoreManager."""

import argparse
import json
import os
import re
import shlex
import sys
from collections.abc import Sequence
from typing import Any

from environment_store.core import EnvironmentStoreManager
from environment_store.core.exceptions import ConfirmationMismatchError
from environment_store.core.hierarchy import (
    LEVELS,
    Path,
    describe,
    level_kind,
    to_kwargs,
    to_path,
)
from environment_store.core.schemas import Variable
from environment_store.picker import PickerCancelled, pick_level

BACKENDS = ("json", "postgres", "ssm", "secretsmanager")
FORMATS = ("dotenv", "export", "json", "table")

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_CONFLICT = 3


class CliError(Exception):
    """An expected, user-facing error. Reported on stderr without a traceback."""


def build_manager(args: argparse.Namespace, prefix: str = "") -> EnvironmentStoreManager:
    """
    Create a manager for the backend selected via options or environment variables.

    ``prefix`` selects the option set: ``""`` for the main store, ``"dest_"`` for the destination
    of ``transfer``.
    """
    flag = "--dest-" if prefix else "--"
    env = "ENVIRONMENT_STORE_DEST_" if prefix else "ENVIRONMENT_STORE_"
    backend = getattr(args, f"{prefix}backend")
    if backend is None:
        raise CliError(
            f"No {'destination ' if prefix else ''}backend selected. Use {flag}backend "
            f"({', '.join(BACKENDS)}) or set {env}BACKEND."
        )

    json_file = getattr(args, f"{prefix}json_file")
    database_url = getattr(args, f"{prefix}database_url")
    store_prefix = getattr(args, f"{prefix}prefix")

    if backend == "json":
        from environment_store.adapters.json.json_file_adapter import JsonFileAdapter

        if not json_file:
            raise CliError(f"The json backend needs {flag}json-file or {env}JSON_FILE.")
        return EnvironmentStoreManager(adapter=JsonFileAdapter(json_file))

    if backend == "postgres":
        from environment_store.adapters.postgresql import PostgreSQLAdapter

        if not database_url:
            raise CliError(
                f"The postgres backend needs {flag}database-url or {env}DATABASE_URL."
            )
        return EnvironmentStoreManager(adapter=PostgreSQLAdapter(database_url))

    region = getattr(args, f"{prefix}region")
    if not region:
        raise CliError(f"The {backend} backend needs {flag}region, {env}REGION or AWS_REGION.")

    if backend == "ssm":
        from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

        return EnvironmentStoreManager(
            adapter=ParameterStoreAdapter(
                region=region,
                prefix=store_prefix or "",
                parameter_type=getattr(args, f"{prefix}parameter_type"),
            )
        )

    from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

    return EnvironmentStoreManager(
        adapter=SecretsManagerAdapter(region=region, prefix=store_prefix or "environment-store")
    )


def _backend_identity(args: argparse.Namespace, prefix: str = "") -> tuple[str | None, ...]:
    """What makes two backend selections point at the same store."""
    backend = getattr(args, f"{prefix}backend")
    if backend == "json":
        json_file = getattr(args, f"{prefix}json_file")
        return (backend, os.path.abspath(json_file) if json_file else None)
    if backend == "postgres":
        return (backend, getattr(args, f"{prefix}database_url"))
    return (backend, getattr(args, f"{prefix}region"), getattr(args, f"{prefix}prefix"))


def _env(name: str) -> str | None:
    return os.environ.get(f"ENVIRONMENT_STORE_{name}")


def _hierarchy(args: argparse.Namespace) -> dict[str, str | None]:
    return {level: getattr(args, level) for level in LEVELS}


def _quote_dotenv(value: str) -> str:
    if value == "" or all(c.isalnum() or c in "_-./:@%+,=" for c in value):
        return value
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def format_variables(variables: Sequence[Variable], fmt: str, show_values: bool = True) -> str:
    variables = sorted(variables, key=lambda v: v.name)
    shown = [(v.name, v.value if show_values else "***") for v in variables]
    if fmt == "json":
        return json.dumps(dict(shown), indent=2)
    if fmt == "export":
        return "\n".join(f"export {name}={shlex.quote(value)}" for name, value in shown)
    if not show_values and fmt == "dotenv":
        return "\n".join(f"{name}=***" for name, _ in shown)
    if fmt == "table":
        if not shown:
            return ""
        width = max(len(name) for name, _ in shown)
        return "\n".join(f"{name.ljust(width)}  {value}" for name, value in shown)
    return "\n".join(f"{name}={_quote_dotenv(value)}" for name, value in shown)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines. Supports comments, `export`, and single/double quotes."""
    result: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            raise CliError(f"Invalid dotenv line {lineno}: {raw!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = (
                value[1:-1]
                .replace("\\n", "\n")
                .replace("\\r", "\r")
                .replace('\\"', '"')
                .replace("\\\\", "\\")
            )
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        result[key] = value
    return result


def _load_import_file(path: str, fmt: str) -> dict[str, str]:
    try:
        if path == "-":
            text = sys.stdin.read()
        else:
            with open(path, encoding="utf-8") as f:
                text = f.read()
    except OSError as exc:
        raise CliError(f"Cannot read {path}: {exc}") from exc
    if fmt == "auto":
        fmt = "json" if path.endswith(".json") or text.lstrip().startswith("{") else "dotenv"
    if fmt == "dotenv":
        return parse_dotenv(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(k, str) for k in data):
        raise CliError("JSON input must be a flat object of NAME: value pairs.")
    if any(isinstance(v, (dict, list)) or v is None for v in data.values()):
        raise CliError("JSON input must be a flat object with scalar values.")
    return {k: _scalar_to_str(v) for k, v in data.items()}


def _scalar_to_str(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _read_value(args: argparse.Namespace) -> str:
    sources = [args.value is not None, args.stdin, args.from_file is not None]
    if sum(sources) != 1:
        raise CliError("Provide exactly one of VALUE, --stdin or --from-file.")
    if args.stdin:
        value = sys.stdin.read()
        return value.removesuffix("\n")
    if args.from_file is not None:
        try:
            with open(args.from_file, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            raise CliError(f"Cannot read {args.from_file}: {exc}") from exc
    return args.value


def _out(text: str) -> None:
    if text:
        print(text)


def cmd_get(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    value = manager.get_variable(args.name, **_hierarchy(args))
    if value is None:
        raise CliError(f"Variable {args.name!r} not found at {_describe(args)}.")
    if args.format == "json":
        _out(json.dumps({"name": args.name, "value": value}))
    else:
        sys.stdout.write(value if args.raw else value + "\n")
    return 0


def cmd_set(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    value = _read_value(args)
    manager.set_variable(args.name, value, **_hierarchy(args))
    print(f"Set {args.name} at {_describe(args)}", file=sys.stderr)
    return 0


def cmd_list(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    hierarchy = _hierarchy(args)
    if args.resolved:
        variables = manager.get_resolved_variables(**hierarchy)
    else:
        variables = manager.get_variables(**hierarchy)
    if args.names_only:
        _out("\n".join(sorted(v.name for v in variables)))
    else:
        _out(format_variables(variables, args.format, show_values=not args.mask))
    return 0


_SHELL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def cmd_export(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    """
    Print the resolved variables of a level as shell code for ``eval``.

    A child process cannot change its parent's environment, so the shell has to evaluate this output.
    """
    variables = manager.get_resolved_variables(**_hierarchy(args))
    invalid = sorted(v.name for v in variables if not _SHELL_NAME.fullmatch(v.name))
    if invalid:
        raise CliError(
            f"Cannot export names that are not valid shell identifiers: {', '.join(invalid)}."
        )
    variables = sorted(variables, key=lambda v: v.name)
    if args.unset:
        _out("\n".join(f"unset {v.name}" for v in variables))
    else:
        _out(format_variables(variables, "export"))
    print(
        f"{'Unsetting' if args.unset else 'Exporting'} {len(variables)} variable(s) "
        f"resolved at {_describe(args)}",
        file=sys.stderr,
    )
    return 0


def cmd_export_dotenv(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    """
    Write the resolved variables of a level to a ``.env`` file.

    ``--file`` may name a file or an existing directory; a directory gets a ``.env`` file inside it.
    The file is created with mode 0600 because values are often secrets.
    """
    path = args.file
    if os.path.isdir(path) or path.endswith(os.sep):
        path = os.path.join(path, ".env")
    variables = manager.get_resolved_variables(**_hierarchy(args))
    invalid = sorted(v.name for v in variables if not _SHELL_NAME.fullmatch(v.name))
    if invalid:
        raise CliError(
            f"Cannot export names that are not valid dotenv identifiers: {', '.join(invalid)}."
        )
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if args.force else os.O_EXCL)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise CliError(f"{path} already exists. Use --force to overwrite it.") from exc
    except OSError as exc:
        raise CliError(f"Cannot write {path}: {exc}") from exc
    content = format_variables(variables, "dotenv")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content + "\n" if content else "")
    print(
        f"Wrote {len(variables)} variable(s) resolved at {_describe(args)} to {path}",
        file=sys.stderr,
    )
    return 0


def cmd_delete(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    if not args.yes and _can_prompt(args):
        answer = input(f"Delete {', '.join(args.names)} at {_describe(args)}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            raise CliError("Aborted.")
    hierarchy = _hierarchy(args)
    if len(args.names) == 1:
        manager.delete_variable(args.names[0], **hierarchy)
    else:
        manager.delete_variables(args.names, **hierarchy)
    print(f"Deleted {', '.join(args.names)} at {_describe(args)}", file=sys.stderr)
    return 0


def cmd_import(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    variables = _load_import_file(args.file, args.input_format)
    if not variables:
        raise CliError("Nothing to import.")
    if args.dry_run:
        _out(
            format_variables(
                [Variable(name=k, value=v) for k, v in variables.items()], "table", False
            )
        )
        print(
            f"Would import {len(variables)} variable(s) at {_describe(args)}", file=sys.stderr
        )
        return 0
    manager.set_variables(variables, **_hierarchy(args))
    print(f"Imported {len(variables)} variable(s) at {_describe(args)}", file=sys.stderr)
    return 0


def cmd_children(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    names = manager.get_child_levels(**_hierarchy(args))
    if args.format == "json":
        _out(json.dumps(names))
    else:
        _out("\n".join(names))
    return 0


def _level_tree(manager: EnvironmentStoreManager, path: Path, depth: int | None) -> dict:
    """The levels below ``path`` as nested ``{name: {...}}`` dicts, ``depth`` levels deep."""
    if depth == 0:
        return {}
    below = None if depth is None else depth - 1
    return {
        name: _level_tree(manager, path + (name,), below)
        for name in manager.get_child_levels(**to_kwargs(path))
    }


def _tree_lines(tree: dict, path: Path, prefix: str = "") -> list[str]:
    lines = []
    for i, (name, below) in enumerate(tree.items()):
        last = i == len(tree) - 1
        child = path + (name,)
        lines.append(f"{prefix}{'└── ' if last else '├── '}{name} ({level_kind(child)})")
        lines.extend(_tree_lines(below, child, prefix + ("    " if last else "│   ")))
    return lines


def _tree_paths(tree: dict, path: Path) -> list[str]:
    lines = []
    for name, below in tree.items():
        child = path + (name,)
        lines.append(describe(child))
        lines.extend(_tree_paths(below, child))
    return lines


def cmd_levels(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    path = to_path(**_hierarchy(args))
    tree = _level_tree(manager, path, args.depth)
    if args.format == "json":
        _out(json.dumps(tree, indent=2))
    elif args.format == "paths":
        _out("\n".join(_tree_paths(tree, path)))
    else:
        head = f"{describe(path)} ({level_kind(path)})" if path else "root"
        _out("\n".join([head, *_tree_lines(tree, path)]))
    return 0


def cmd_delete_level(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    hierarchy = _hierarchy(args)
    path = to_path(**hierarchy)
    if not path:
        raise CliError("Give at least --organisation: the root level cannot be deleted.")
    variables, sub_levels = manager.count_level(**hierarchy)
    name, where = path[-1], _describe(args)
    summary = (
        f"{level_kind(path)} {name!r} ({where}): {sub_levels} level(s) below it, "
        f"{variables} variable(s) in total"
    )
    if args.dry_run:
        print(f"Would delete {summary}", file=sys.stderr)
        return 0
    confirm = args.confirm
    if confirm is None:
        if not _can_prompt(args):
            raise CliError(
                f"Pass --confirm {name} to delete the {level_kind(path)} non-interactively."
            )
        print(f"WARNING: this permanently deletes {summary}.", file=sys.stderr)
        confirm = input(f"Type '{name}' to confirm: ")
    deleted = manager.delete_level(**hierarchy, confirm=confirm)
    print(f"Deleted {level_kind(path)} {name!r} ({deleted} variable(s))", file=sys.stderr)
    return 0


def cmd_transfer(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    if _backend_identity(args) == _backend_identity(args, "dest_"):
        raise CliError("Source and destination are the same store.")
    destination = build_manager(args, "dest_")
    result = destination.import_from(
        manager, **_hierarchy(args), overwrite=args.overwrite, dry_run=args.dry_run
    )
    if args.format == "json":
        _out(result.model_dump_json(indent=2))
    else:
        for conflict in result.conflicts:
            where = describe(tuple(conflict.path))
            print(
                f"conflict: {conflict.name} at {where} differs in the destination",
                file=sys.stderr,
            )
    verb = "Would transfer" if args.dry_run else "Transferred"
    scope = _describe(args) if any(_hierarchy(args).values()) else "the whole store"
    print(
        f"{verb} {scope} from {args.backend} to {args.dest_backend}: {result.levels} level(s), "
        f"{result.created} created, {result.updated} updated, {result.unchanged} unchanged, "
        f"{result.skipped} skipped",
        file=sys.stderr,
    )
    if result.skipped:
        print(
            "Skipped variables already exist with a different value; use --overwrite to replace them.",
            file=sys.stderr,
        )
        return EXIT_CONFLICT
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    if args.backend != "postgres":
        raise CliError(
            "migrate is only available for the postgres backend (--backend postgres)."
        )
    if not args.database_url:
        raise CliError(
            "The postgres backend needs --database-url or ENVIRONMENT_STORE_DATABASE_URL."
        )
    from environment_store.adapters.postgresql import apply_migrations, pending_migrations

    if args.status:
        pending = pending_migrations(args.database_url)
        for migration_id in pending:
            print(migration_id)
        print(f"{len(pending)} pending migration(s)", file=sys.stderr)
        return 0
    applied = apply_migrations(args.database_url)
    for migration_id in applied:
        print(migration_id)
    print(
        f"Applied {len(applied)} migration(s)" if applied else "Database is up to date",
        file=sys.stderr,
    )
    return 0


def cmd_tui(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    try:
        from environment_store.tui import run
    except ImportError as exc:
        raise CliError(
            "The TUI needs the tui extra: pip install 'environment-store[tui]'."
        ) from exc
    run(manager)
    return 0


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def _can_prompt(args: argparse.Namespace) -> bool:
    """Whether the user may be asked something: on a terminal and without --no-interaction."""
    return not args.no_interaction and sys.stdin.isatty()


def _resolve_level(manager: EnvironmentStoreManager, args: argparse.Namespace) -> None:
    """
    Fill in -o/-p/-e/-s from the interactive level picker when a command was given none of them.

    Only on a terminal, and not with --root or --no-interaction. ``args.pick`` is ``"any"`` when the root level may
    be chosen and ``"below-root"`` when it may not.
    """
    pick = getattr(args, "pick", None)
    if pick is None:
        return
    given = any(_hierarchy(args).values())
    if args.root:
        if given:
            raise CliError("--root cannot be combined with -o/-p/-e/-s.")
        return
    if given or args.no_interaction or not _interactive():
        return
    allow_root = pick == "any"
    if allow_root and not manager.get_child_levels():
        return  # nothing to choose from but the root level
    try:
        path = pick_level(
            lambda path: manager.get_child_levels(**to_kwargs(path)),
            f"Choose the level for {args.command}:",
            allow_root=allow_root,
        )
    except PickerCancelled as exc:
        raise CliError(str(exc) or "Aborted.") from exc
    for level, value in to_kwargs(path).items():
        setattr(args, level, value)
    where = f"{describe(path)} ({level_kind(path)})" if path else "root"
    print(f"Level: {where}", file=sys.stderr)


def _describe(args: argparse.Namespace) -> str:
    return describe(to_path(**_hierarchy(args)))


HIERARCHY_HELP = (
    "Variables live on a level of the hierarchy root > organisation > project > environment > "
    "service. A deeper level is addressed by naming every level above it, so levels cannot be "
    "skipped: -p needs -o, -e needs -p and -s needs -e. Names are case-sensitive. "
    "Run `environment-store levels` to see which levels exist."
)
PICKER_HELP = (
    "Without any of these options the command works on the root level. On a terminal it first "
    "lets you pick the level from a tree of the existing levels instead; pass --root (or "
    "--no-interaction) to skip that."
)
NO_INTERACTION_HELP = (
    "never prompt, as if there were no terminal: no level picker (no -o/-p/-e/-s means the root "
    "level), delete does not ask, delete-level needs --confirm (ENVIRONMENT_STORE_NO_INTERACTION)"
)
LEVEL_EXAMPLES = """\
level examples:
  (no options)                      root level, shared by every organisation
  -o acme                           organisation acme
  -o acme -p webapp                 project webapp of acme
  -o acme -p webapp -e prod         environment prod of that project
  -o acme -p webapp -e prod -s api  service api of that environment"""


class _HelpFormatter(argparse.HelpFormatter):
    """Wraps text paragraph by paragraph and keeps indented lines (examples) as written."""

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        blocks = []
        for block in text.split("\n\n"):
            if "\n " in block:
                blocks.append("\n".join(indent + line for line in block.splitlines()))
            else:
                blocks.append(super()._fill_text(block, width, indent))
        return "\n\n".join(blocks)


def _hierarchy_parser(pick: bool) -> argparse.ArgumentParser:
    """
    The -o/-p/-e/-s options. With ``pick`` the command opens the level picker when none are given.
    """
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_argument_group(
        "hierarchy", f"{HIERARCHY_HELP}\n\n{PICKER_HELP}" if pick else HIERARCHY_HELP
    )
    group.add_argument(
        "-o",
        "--organisation",
        metavar="NAME",
        help="organisation, the top level below root (e.g. acme)",
    )
    group.add_argument(
        "-p", "--project", metavar="NAME", help="project inside the organisation (needs -o)"
    )
    group.add_argument(
        "-e",
        "--environment",
        metavar="NAME",
        help="environment of the project, e.g. dev or prod (needs -o and -p)",
    )
    group.add_argument(
        "-s",
        "--service",
        metavar="NAME",
        help="service in the environment, e.g. api (needs -o, -p and -e)",
    )
    if pick:
        group.add_argument(
            "--root",
            action="store_true",
            help="use the root level without asking (only without -o/-p/-e/-s)",
        )
        group.add_argument(
            "--no-interaction",
            action="store_true",
            default=argparse.SUPPRESS,  # keep the value of the global option
            help=NO_INTERACTION_HELP,
        )
    return parent


def _add_backend_options(group: argparse._ArgumentGroup, dest: bool) -> None:
    """Add the backend options. With ``dest`` they select the destination of ``transfer``."""
    flag, key, env, name = (
        ("--dest-", "dest_", "DEST_", "destination ") if dest else ("--", "", "", "")
    )
    var = f"ENVIRONMENT_STORE_{env}"
    group.add_argument(
        f"{flag}backend",
        dest=f"{key}backend",
        choices=BACKENDS,
        default=_env(f"{env}BACKEND"),
        help=f"{name}storage backend ({var}BACKEND)",
    )
    group.add_argument(
        f"{flag}json-file",
        dest=f"{key}json_file",
        default=_env(f"{env}JSON_FILE"),
        help=f"json backend: file path ({var}JSON_FILE)",
    )
    group.add_argument(
        f"{flag}database-url",
        dest=f"{key}database_url",
        default=_env(f"{env}DATABASE_URL"),
        help=f"postgres backend: SQLAlchemy URL ({var}DATABASE_URL)",
    )
    group.add_argument(
        f"{flag}region",
        dest=f"{key}region",
        default=_env(f"{env}REGION") or os.environ.get("AWS_REGION"),
        help=f"ssm/secretsmanager: AWS region ({var}REGION, AWS_REGION)",
    )
    group.add_argument(
        f"{flag}prefix",
        dest=f"{key}prefix",
        default=_env(f"{env}PREFIX"),
        help=f"ssm/secretsmanager: name prefix ({var}PREFIX)",
    )
    group.add_argument(
        f"{flag}parameter-type",
        dest=f"{key}parameter_type",
        choices=("String", "SecureString"),
        default=_env(f"{env}PARAMETER_TYPE") or "SecureString",
        help=f"ssm: parameter type ({var}PARAMETER_TYPE, default SecureString)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="environment-store",
        description=(
            "Manage hierarchical environment variables in a persistent store.\n\n"
            f"{HIERARCHY_HELP} Run `environment-store COMMAND -h` for the options of a command."
        ),
        epilog=LEVEL_EXAMPLES,
        formatter_class=_HelpFormatter,
    )
    _add_backend_options(
        parser.add_argument_group(
            "backend", "Each option can also be set via the ENVIRONMENT_STORE_* variable shown."
        ),
        dest=False,
    )
    parser.add_argument(
        "--no-interaction",
        action="store_true",
        default=(_env("NO_INTERACTION") or "").lower() in ("1", "true", "yes", "on"),
        help=NO_INTERACTION_HELP,
    )

    hierarchy = _hierarchy_parser(pick=True)
    hierarchy_no_pick = _hierarchy_parser(pick=False)
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str, **kwargs: Any) -> argparse.ArgumentParser:
        kwargs.setdefault("epilog", LEVEL_EXAMPLES)
        return subparsers.add_parser(name, formatter_class=_HelpFormatter, **kwargs)

    p = add("get", parents=[hierarchy], help="print one variable's value")
    p.add_argument("name")
    p.add_argument("--format", choices=("raw", "json"), default="raw")
    p.add_argument("--raw", action="store_true", help="do not append a trailing newline")
    p.set_defaults(func=cmd_get, pick="any")

    p = add("set", parents=[hierarchy], help="create or update a variable")
    p.add_argument("name")
    p.add_argument("value", nargs="?", help="value (or use --stdin / --from-file)")
    p.add_argument("--stdin", action="store_true", help="read the value from stdin")
    p.add_argument("--from-file", help="read the value from a file")
    p.set_defaults(func=cmd_set, pick="any")

    p = add("list", aliases=["ls"], parents=[hierarchy], help="list variables")
    p.add_argument("--format", choices=FORMATS, default="dotenv")
    p.add_argument(
        "--resolved",
        action="store_true",
        help="merge in parent levels; deeper levels override shallower ones",
    )
    p.add_argument("--names-only", action="store_true", help="print only variable names")
    p.add_argument("--mask", action="store_true", help="hide values (shown as ***)")
    p.set_defaults(func=cmd_list, pick="any")

    p = add(
        "export",
        parents=[hierarchy],
        help="print the resolved variables of a level as shell code, to load with eval",
        description=(
            "Print the resolved variables (parent levels included, deeper levels win) as "
            "`export NAME='value'` lines. A program cannot change its parent shell's environment, "
            'so load them with: eval "$(environment-store export -o acme -p webapp)"'
        ),
    )
    p.add_argument(
        "--unset",
        action="store_true",
        help="print `unset NAME` lines instead, to remove the variables again",
    )
    p.set_defaults(func=cmd_export, pick="any")

    p = add(
        "export-dotenv",
        parents=[hierarchy],
        help="write the resolved variables of a level to a .env file",
        description=(
            "Write the resolved variables (parent levels included, deeper levels win) as "
            "NAME=value lines to a .env file (default: ./.env). An existing file is only "
            "replaced with --force."
        ),
    )
    p.add_argument(
        "-f",
        "--file",
        default=".env",
        metavar="PATH",
        help="file to write, or a directory to write .env into (default: .env)",
    )
    p.add_argument("--force", action="store_true", help="overwrite the file if it exists")
    p.set_defaults(func=cmd_export_dotenv, pick="any")

    p = add("delete", aliases=["rm"], parents=[hierarchy], help="delete variables")
    p.add_argument("names", nargs="+", metavar="name")
    p.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    p.set_defaults(func=cmd_delete, pick="any")

    p = add("import", parents=[hierarchy], help="set many variables from a .env or JSON file")
    p.add_argument("file", help="path to the file, or - for stdin")
    p.add_argument("--input-format", choices=("auto", "dotenv", "json"), default="auto")
    p.add_argument("--dry-run", action="store_true", help="show names without writing")
    p.set_defaults(func=cmd_import, pick="any")

    p = add(
        "delete-level",
        aliases=["rm-level"],
        parents=[hierarchy],
        help="delete a level (organisation, project, ...) with everything below it",
    )
    p.add_argument(
        "--confirm",
        metavar="NAME",
        help="the exact name of the level to delete (prompted for on a terminal if omitted)",
    )
    p.add_argument("--dry-run", action="store_true", help="show what would be deleted")
    p.set_defaults(func=cmd_delete_level, pick="below-root")

    p = add(
        "levels",
        aliases=["tree"],
        parents=[hierarchy_no_pick],
        help="show the existing levels (organisations, projects, ...) as a tree",
        description=(
            "Show the levels that exist in the store as a tree, with the kind of each level. "
            "Use -o/-p/-e/-s to show only the levels below that level. A level exists as long "
            "as it or a level below it holds a variable."
        ),
    )
    p.add_argument(
        "--format",
        choices=("tree", "paths", "json"),
        default="tree",
        help="tree (default), paths (one 'acme / webapp / dev' per line) or json (nested object)",
    )
    p.add_argument(
        "--depth", type=int, metavar="N", help="show at most N levels below the starting level"
    )
    p.set_defaults(func=cmd_levels)

    p = add(
        "children",
        parents=[hierarchy_no_pick],
        help="list child levels: organisations, or the projects/environments/services below a level",
    )
    p.add_argument("--format", choices=("lines", "json"), default="lines")
    p.set_defaults(func=cmd_children)

    p = add(
        "transfer",
        parents=[hierarchy_no_pick],
        help="copy variables from this store (the main backend options) to another backend",
        description=(
            "Copy the variables of the main store (--backend ...) into the destination store "
            "(--dest-backend ...), keeping the hierarchy. Use -o/-p/-e/-s to copy only a subtree. "
            "Existing variables with a different value are skipped unless --overwrite is given. "
            "The source is never modified. Exit code 3 means some variables were skipped."
        ),
    )
    _add_backend_options(p.add_argument_group("destination backend"), dest=True)
    p.add_argument(
        "--overwrite", action="store_true", help="replace differing destination values"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="report what would happen, write nothing"
    )
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_transfer)

    p = add(
        "migrate", epilog=None, help="apply the database migrations (postgres backend only)"
    )
    p.add_argument(
        "--status", action="store_true", help="only list pending migrations, apply nothing"
    )
    p.set_defaults(func=cmd_migrate, needs_manager=False)

    p = add(
        "tui", epilog=None, help="open the interactive terminal UI (requires the tui extra)"
    )
    p.set_defaults(func=cmd_tui)

    return parser


def main(
    argv: Sequence[str] | None = None, manager: EnvironmentStoreManager | None = None
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if not getattr(args, "needs_manager", True):
            return args.func(args)
        if manager is None:
            manager = build_manager(args)
        _resolve_level(manager, args)
        return args.func(manager, args)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except ConfirmationMismatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ImportError as exc:
        print(
            f"error: missing dependency for backend {args.backend!r}: {exc}. "
            "Install the matching extra (environment-store[aws] or [postgres]).",
            file=sys.stderr,
        )
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - adapter/backend failures (e.g. VariableNotFoundError)
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
