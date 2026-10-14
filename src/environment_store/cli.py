"""Command line interface for the EnvironmentStoreManager."""

import argparse
import json
import os
import shlex
import sys
from collections.abc import Sequence
from typing import Any

from environment_store.core import EnvironmentStoreManager
from environment_store.core.schemas import Variable

BACKENDS = ("json", "postgres", "ssm", "secretsmanager")
LEVELS = ("organisation", "project", "environment", "service")
FORMATS = ("dotenv", "export", "json", "table")

EXIT_ERROR = 1
EXIT_USAGE = 2


class CliError(Exception):
    """An expected, user-facing error. Reported on stderr without a traceback."""


def build_manager(args: argparse.Namespace) -> EnvironmentStoreManager:
    """Create a manager for the backend selected via options or environment variables."""
    backend = args.backend
    if backend is None:
        raise CliError(
            f"No backend selected. Use --backend ({', '.join(BACKENDS)}) "
            "or set ENVIRONMENT_STORE_BACKEND."
        )

    if backend == "json":
        from environment_store.adapters.json.json_file_adapter import JsonFileAdapter

        if not args.json_file:
            raise CliError("The json backend needs --json-file or ENVIRONMENT_STORE_JSON_FILE.")
        return EnvironmentStoreManager(adapter=JsonFileAdapter(args.json_file))

    if backend == "postgres":
        from environment_store.adapters.postgresql import PostgreSQLAdapter

        if not args.database_url:
            raise CliError(
                "The postgres backend needs --database-url or ENVIRONMENT_STORE_DATABASE_URL."
            )
        return EnvironmentStoreManager(adapter=PostgreSQLAdapter(args.database_url))

    if backend == "ssm":
        from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

        return EnvironmentStoreManager(
            adapter=ParameterStoreAdapter(
                region=_require_region(args),
                prefix=args.prefix or "",
                parameter_type=args.parameter_type,
            )
        )

    from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

    return EnvironmentStoreManager(
        adapter=SecretsManagerAdapter(
            region=_require_region(args), prefix=args.prefix or "environment-store"
        )
    )


def _require_region(args: argparse.Namespace) -> str:
    if not args.region:
        raise CliError(
            f"The {args.backend} backend needs --region, ENVIRONMENT_STORE_REGION or AWS_REGION."
        )
    return args.region


def _env(name: str) -> str | None:
    return os.environ.get(f"ENVIRONMENT_STORE_{name}")


def _hierarchy(args: argparse.Namespace) -> dict[str, str | None]:
    return {level: getattr(args, level) for level in LEVELS}


def _depth(hierarchy: dict[str, str | None]) -> int:
    return sum(1 for value in hierarchy.values() if value is not None)


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
        variables = _resolved(manager, hierarchy)
    else:
        variables = manager.get_variables(**hierarchy)
    if args.names_only:
        _out("\n".join(sorted(v.name for v in variables)))
    else:
        _out(format_variables(variables, args.format, show_values=not args.mask))
    return 0


def _resolved(
    manager: EnvironmentStoreManager, hierarchy: dict[str, str | None]
) -> list[Variable]:
    """Variables merged down the hierarchy, deeper levels overriding shallower ones."""
    depth = _depth(hierarchy)
    org, project, env, service = (hierarchy[level] for level in LEVELS)
    if any(hierarchy[LEVELS[i]] is None for i in range(depth)):
        raise ValueError(
            "hierarchy levels cannot be skipped (organisation > project > environment > service)"
        )
    if depth == 0:
        return manager.get_root_variables()
    assert org is not None
    if depth == 1:
        return manager.get_organisation_variables(org)
    assert project is not None
    if depth == 2:
        return manager.get_project_variables(org, project)
    assert env is not None
    if depth == 3:
        return manager.get_environment_variables(org, project, env)
    assert service is not None
    return manager.get_service_variables(org, project, env, service)


def cmd_delete(manager: EnvironmentStoreManager, args: argparse.Namespace) -> int:
    if not args.yes and sys.stdin.isatty():
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
    h = _hierarchy(args)
    org, project, env = h["organisation"], h["project"], h["environment"]
    if h["service"] is not None:
        raise CliError("Services have no children.")
    if org is None:
        names = manager.get_organisations()
    elif project is None:
        names = manager.get_projects(org)
    elif env is None:
        names = manager.get_environments(org, project)
    else:
        names = manager.get_services(org, project, env)
    if args.format == "json":
        _out(json.dumps(sorted(names)))
    else:
        _out("\n".join(sorted(names)))
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


def _describe(args: argparse.Namespace) -> str:
    parts = [f"{level}={getattr(args, level)}" for level in LEVELS if getattr(args, level)]
    return " ".join(parts) if parts else "root level"


def _hierarchy_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    group = parent.add_argument_group(
        "hierarchy (organisation > project > environment > service)"
    )
    group.add_argument("-o", "--organisation", help="organisation (default: root level)")
    group.add_argument("-p", "--project", help="project (requires --organisation)")
    group.add_argument("-e", "--environment", help="environment (requires --project)")
    group.add_argument("-s", "--service", help="service (requires --environment)")
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="environment-store",
        description="Manage hierarchical environment variables in a persistent store.",
    )
    backend = parser.add_argument_group(
        "backend", "Each option can also be set via the ENVIRONMENT_STORE_* variable shown."
    )
    backend.add_argument(
        "--backend",
        choices=BACKENDS,
        default=_env("BACKEND"),
        help="storage backend (ENVIRONMENT_STORE_BACKEND)",
    )
    backend.add_argument(
        "--json-file",
        default=_env("JSON_FILE"),
        help="json backend: file path (ENVIRONMENT_STORE_JSON_FILE)",
    )
    backend.add_argument(
        "--database-url",
        default=_env("DATABASE_URL"),
        help="postgres backend: SQLAlchemy URL (ENVIRONMENT_STORE_DATABASE_URL)",
    )
    backend.add_argument(
        "--region",
        default=_env("REGION") or os.environ.get("AWS_REGION"),
        help="ssm/secretsmanager: AWS region (ENVIRONMENT_STORE_REGION, AWS_REGION)",
    )
    backend.add_argument(
        "--prefix",
        default=_env("PREFIX"),
        help="ssm/secretsmanager: name prefix (ENVIRONMENT_STORE_PREFIX)",
    )
    backend.add_argument(
        "--parameter-type",
        choices=("String", "SecureString"),
        default=_env("PARAMETER_TYPE") or "SecureString",
        help="ssm: parameter type (ENVIRONMENT_STORE_PARAMETER_TYPE, default SecureString)",
    )

    hierarchy = _hierarchy_parser()
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("get", parents=[hierarchy], help="print one variable's value")
    p.add_argument("name")
    p.add_argument("--format", choices=("raw", "json"), default="raw")
    p.add_argument("--raw", action="store_true", help="do not append a trailing newline")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", parents=[hierarchy], help="create or update a variable")
    p.add_argument("name")
    p.add_argument("value", nargs="?", help="value (or use --stdin / --from-file)")
    p.add_argument("--stdin", action="store_true", help="read the value from stdin")
    p.add_argument("--from-file", help="read the value from a file")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("list", aliases=["ls"], parents=[hierarchy], help="list variables")
    p.add_argument("--format", choices=FORMATS, default="dotenv")
    p.add_argument(
        "--resolved",
        action="store_true",
        help="merge in parent levels; deeper levels override shallower ones",
    )
    p.add_argument("--names-only", action="store_true", help="print only variable names")
    p.add_argument("--mask", action="store_true", help="hide values (shown as ***)")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", aliases=["rm"], parents=[hierarchy], help="delete variables")
    p.add_argument("names", nargs="+", metavar="name")
    p.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser(
        "import", parents=[hierarchy], help="set many variables from a .env or JSON file"
    )
    p.add_argument("file", help="path to the file, or - for stdin")
    p.add_argument("--input-format", choices=("auto", "dotenv", "json"), default="auto")
    p.add_argument("--dry-run", action="store_true", help="show names without writing")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser(
        "children",
        parents=[hierarchy],
        help="list child levels: organisations, or the projects/environments/services below a level",
    )
    p.add_argument("--format", choices=("lines", "json"), default="lines")
    p.set_defaults(func=cmd_children)

    p = sub.add_parser("migrate", help="apply the database migrations (postgres backend only)")
    p.add_argument(
        "--status", action="store_true", help="only list pending migrations, apply nothing"
    )
    p.set_defaults(func=cmd_migrate, needs_manager=False)

    p = sub.add_parser("tui", help="open the interactive terminal UI (requires the tui extra)")
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
        return args.func(manager, args)
    except CliError as exc:
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
