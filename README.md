# Environment store

This library provides a simple interface to manage environment variables on different cloud providers and also locally.
It provides a high level `EnvironmentStoreManager` class that can be used to store and retrieve hierarchical
environment variables.

## Hierarchical variables

You can organise your variables in a hierarchical structure:
Organization > Project > Environment > Service > Variable

Each level can have a set of variables. Variables are unique within a level, but not across levels.

```
Org_1
├── Project_1
│   ├── Environment_1
│   │   ├── Service_1
│   │   │   ├── Variable_1
│   │   │   └── Variable_2
│   │   └── Service_2
│   │       ├── Variable_3
│   │       └── Variable_4
│   └── Environment_2
│       ├── Service_3
│       │   ├── Variable_5
│       │   └── Variable_6
│       └── Service_4
│           ├── Variable_7
│           └── Variable_8
└── Project_2
    ├── Environment_3
    │   ├── Service_5
    │   │   ├── Variable_9
    │   │   └── Variable_10
    │   └── Service_6
    │       ├── Variable_11
    │       └── Variable_12
    └── Environment_4
        ├── Service_7
        │   ├── Variable_13
        │   └── Variable_14
        └── Service_8
            ├── Variable_15
            └── Variable_16
```

Alternatively you can also use this library without the hierarchical structure:

```
├── Variable_1
├── Variable_2
├── Variable_3
├── Variable_4
├── Variable_5
├── Variable_6
├── Variable_7
├── Variable_8
├── Variable_9
├── Variable_10
├── Variable_11
├── Variable_12
├── Variable_13
├── Variable_14
├── Variable_15
└── Variable_16
```

## Installation

The core package only depends on `pydantic`. The storage backends bring their own dependencies as extras:

| Extra      | Adds                                                   |
|------------|--------------------------------------------------------|
| _(none)_   | core + `JsonFileAdapter`                               |
| `aws`      | `ParameterStoreAdapter`, `SecretsManagerAdapter` (boto3) |
| `postgres` | `PostgreSQLAdapter` (psycopg, sqlalchemy, yoyo-migrations) |
| `tui`      | terminal UI, `environment-store tui` ([Textual](https://textual.textualize.io/)) |
| `full`     | everything above: `aws` + `postgres` + `tui`           |

### With uv

Add it to your uv project (this updates `pyproject.toml` and the lockfile):

```bash
uv add environment-store                 # core + JsonFileAdapter
uv add "environment-store[aws]"          # + AWS adapters
uv add "environment-store[postgres]"     # + PostgreSQL adapter
uv add "environment-store[aws,postgres]" # multiple extras
uv add "environment-store[full]"         # all extras
```

If the package is not published to an index you can use, install it straight from the repository:

```bash
uv add "environment-store[aws] @ git+https://github.com/mkaufhol/environment-store"
```

Pin a branch, tag or commit by appending `@<ref>` to the URL, e.g. `...environment-store@v0.1.0`.

Without a uv project (e.g. for a quick script or an existing virtual environment), use the pip interface:

```bash
uv pip install "environment-store[aws]"
```

### With pip

```bash
pip install "environment-store[aws]"
```

### Transferring a store to another backend

`transfer` copies every variable from the main store (the usual `--backend ...` options) into a destination
store (the same options with a `--dest-` prefix, or `ENVIRONMENT_STORE_DEST_*` variables), keeping the hierarchy.
Use it to move from a local JSON file to AWS or PostgreSQL, or between any two backends:

```bash
# JSON file -> PostgreSQL (run `environment-store migrate` on the destination first)
environment-store --backend json --json-file ./store.json transfer \
  --dest-backend postgres --dest-database-url postgresql+psycopg://user:pw@localhost/environment_store

# only one project, to AWS Parameter Store; preview first
environment-store --backend json --json-file ./store.json transfer -o acme -p web --dry-run \
  --dest-backend ssm --dest-region eu-central-1 --dest-prefix myapp
```

- The source is never modified; to "move", delete the source yourself after checking the result.
- Variables that do not exist in the destination are created, identical ones are left alone. Variables that
  exist with a **different** value are skipped and listed, and the command exits with code `3`; add `--overwrite`
  to replace them.
- `--dry-run` reports what would happen without writing, `--format json` prints the result as JSON.
- Source and destination must be different stores. Only variables are transferred, not backend specifics
  such as timestamps.

The logic is `EnvironmentStoreManager.import_from(source, ...)`, so other frontends can reuse it.

## Terminal UI

An interactive terminal UI built with [Textual](https://textual.textualize.io/). It needs the `tui` extra
(or `full`):

```bash
uv add "environment-store[tui]"
```

### Starting it

It takes the same backend options as the CLI (`--backend`, `--json-file`, `--database-url`, `--region`,
`--prefix`, or the matching `ENVIRONMENT_STORE_*` variables). Backend options go before `tui`:

```bash
environment-store --backend json --json-file ./store.json tui

# or with environment variables
export ENVIRONMENT_STORE_BACKEND=postgres
export ENVIRONMENT_STORE_DATABASE_URL=postgresql+psycopg://user:pass@localhost/envstore
environment-store tui
```

Without installing it into a project, you can also run it once with `uvx`:

```bash
uvx --from "environment-store[tui]" environment-store --backend json --json-file ./store.json tui
```

### Usage

The left pane is the hierarchy tree (organisation > project > environment > service); nodes load their
children when expanded. The right pane lists the variables of the selected level. Values are hidden (`***`)
until you press `v`.

| Key      | Action                                                              |
|----------|---------------------------------------------------------------------|
| `↑` `↓` / `k` `j` | move up / down; selecting a tree node shows that level's variables |
| `→` / `l` | in the tree: expand the node, then step into its first child; on a node without children switch to the variables table |
| `←` / `h` | in the tree: collapse the node, or go to its parent if it is collapsed; in the table: back to the tree |
| `a`      | add a variable at the selected level                                |
| `e`      | edit the highlighted variable                                       |
| `d`      | delete the highlighted variable (asks for confirmation)             |
| `n`      | new child level (organisation at root, then project, environment, service); asks for a name and a first variable, since a level exists once it holds a variable |
| `r`      | toggle the resolved view (merged with parent levels, deeper wins)   |
| `x`      | delete the selected level with everything below it; you must type its name to confirm |
| `v`      | show / hide values                                                  |
| `F5`     | reload the tree and the table                                       |
| `q`      | quit                                                                |

In the resolved view the table is read-only; switch it off with `r` to edit or delete.

## EnvironmentStoreManager usage

### Initialization

To initialize the `EnvironmentStoreManager` you need to provide an adapter that implements the `AbstractAdapter` interface.
The available adapters are listed below.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

adapter = ParameterStoreAdapter(region="us-east-1")
manager = EnvironmentStoreManager(adapter=adapter)
```

### Reading and writing variables

```python
manager.set_variable("DB_HOST", "localhost", organisation="acme", project="webapp")
manager.set_variables({"LOG_LEVEL": "INFO"}, organisation="acme")

manager.get_variable("DB_HOST", organisation="acme", project="webapp")  # exact level only
manager.get_variables(organisation="acme")  # exact level only

# Merge the variables of a level with all of its parent levels, child values win
manager.get_service_variables("acme", "webapp", "dev", "api")
manager.get_variables_as_dict(
    organisation="acme", project="webapp"
)  # exact level, as {name: value}

manager.get_organisations()
manager.get_projects("acme")
manager.delete_variable("DB_HOST", organisation="acme", project="webapp")
```

A level can only be addressed if all of its parents are given (a `service` needs an `environment`, a `project`
needs an `organisation`, ...), otherwise a `ValueError` is raised.

## Command line interface

The package installs an `environment-store` command (also `python -m environment_store`).
Select a backend with `--backend json|postgres|ssm|secretsmanager` (or `ENVIRONMENT_STORE_BACKEND`);
see `environment-store --help` for the backend options and their `ENVIRONMENT_STORE_*` variables.

```bash
export ENVIRONMENT_STORE_BACKEND=json ENVIRONMENT_STORE_JSON_FILE=./store.json

environment-store set DB_HOST localhost -o acme -p web -e dev
environment-store get DB_HOST -o acme -p web -e dev
environment-store list -o acme -p web -e dev --resolved --format json
environment-store import .env -o acme -p web -e dev
environment-store children -o acme
environment-store delete DB_HOST -o acme -p web -e dev --yes
environment-store delete-level -o acme -p web --dry-run          # what would be removed?
environment-store delete-level -o acme -p web --confirm web      # project and everything below it
```

`delete-level` removes a level (organisation, project, environment or service) together with all of its
variables and every level below it. The root level cannot be deleted. You must confirm with the exact name of
the level: pass `--confirm NAME`, or on a terminal type the name when prompted (the same check as in the TUI).

An agent skill describing efficient CLI usage lives in
[.claude/skills/environment-store-cli/SKILL.md](.claude/skills/environment-store-cli/SKILL.md).

---

# Local file storage

## JsonFileAdapter

The `JsonFileAdapter` stores the environment variables in a local JSON file. It is useful for testing and development purposes.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

adapter = JsonFileAdapter("path/to/file.json")
manager = EnvironmentStoreManager(adapter=adapter)
```

# Databases

## PostgreSQLAdapter

Stores the variables in one table of a PostgreSQL database (version 15+). Install the `postgres` extra.

The schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/) migrations (shipped inside the
package, `yoyo-migrations` comes with the `postgres` extra) which you have to apply before using the adapter.

### Running the migrations with the CLI

```bash
export ENVIRONMENT_STORE_BACKEND=postgres
export ENVIRONMENT_STORE_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/environment_store

environment-store migrate --status   # list pending migrations, apply nothing
environment-store migrate            # apply all pending migrations (safe to re-run)
```

Or without environment variables: `environment-store --backend postgres --database-url <url> migrate`.
The database itself must already exist. `migrate` prints the ids of the applied migrations and
only works with `--backend postgres`.

### Running the migrations from Python

```python
from environment_store.adapters.postgresql import apply_migrations, pending_migrations

pending_migrations(url)  # -> list of migration ids
apply_migrations(url)  # -> list of applied migration ids
```

### Running the migrations from a clone

If you work on the repository you can also use the yoyo CLI directly. Copy
`src/environment_store/adapters/postgresql/yoyo-database-example.ini` to `yoyo-database.ini` in the same directory,
point it to your database and run:

```bash
src/environment_store/adapters/postgresql/scripts/init_database.sh
```

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.postgresql import PostgreSQLAdapter

# Either a SQLAlchemy engine or a database URL
adapter = PostgreSQLAdapter(
    "postgresql+psycopg://user:password@localhost:5432/environment_store"
)
manager = EnvironmentStoreManager(adapter=adapter)
```

# Cloud providers

## AWS

Install the `aws` extra. The connection to AWS works the same way as for boto3 (environment variables, shared
credentials file, instance roles, ...):
https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration

Names (organisation, project, environment, service, variable and prefix segments) may only contain `a-zA-Z0-9_.-`.

### ParameterStoreAdapter

Stores every variable as one AWS Parameter Store parameter. The hierarchy is the parameter path:
`/<prefix>/<organisation>/<project>/<environment>/<service>/<NAME>` (root variables live at `/<NAME>`).
Values are written as `SecureString` by default (`parameter_type="String"` to change that).

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

adapter = ParameterStoreAdapter(region="us-east-1", prefix="myapp")
manager = EnvironmentStoreManager(adapter=adapter)
```

The underlying `ParameterStore` class is a simple wrapper around the boto3 ssm client and can also be used standalone.

### SecretsManagerAdapter

Stores each hierarchy level as **one** Secrets Manager secret holding a JSON object of its variables, e.g.
`myapp/acme/webapp/dev/api` -> `{"DB_HOST": "...", "DB_PORT": "..."}`. The root level is the secret named
`<prefix>` (default `environment-store`). This keeps the number of billed secrets low, but updates are
read-modify-write: concurrent writers on the same level can overwrite each other (last write wins).
A level's secret is deleted (without recovery window) once its last variable is deleted.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

adapter = SecretsManagerAdapter(region="us-east-1", prefix="myapp")
manager = EnvironmentStoreManager(adapter=adapter)
```

---

# Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
- To install the dependencies, run `uv sync` (installs the dev, testing and stubs groups).
- To build the package, run `uv build`.
- To run the tests, run `uv run pytest`. The PostgreSQL tests are skipped unless
  `ENVIRONMENT_STORE_TEST_POSTGRES_URL` points to a throwaway database (its `environment_store` table is truncated).
- To lint and format, run `uv run ruff check` and `uv run ruff format`.
- To type check, run `uv run ty check`.

This project uses pre-commit for code quality checks. To install the pre-commit hooks, run `pre-commit install`.

## Architecture: one shared layer

The CLI (`environment_store/cli.py`), the TUI (`environment_store/tui/`) and any future frontend such as an API
or web app are thin presentation layers over `EnvironmentStoreManager`. **All logic lives in the core layer**
(`environment_store/core/`): hierarchy rules and helpers (`core/hierarchy.py`), listing child levels
(`get_child_levels`), merged variables (`get_resolved_variables`), counting and recursively deleting a level
(`count_level`, `delete_level`) including the safety check that the exact level name is confirmed.

When you add a feature, add it to the manager first and call it from the frontends. A frontend should only
parse input, call the manager and render the result. Keep the CLI and TUI feature-equivalent
(`x` in the TUI is `delete-level` in the CLI, `n` is `set` on a new path, and so on). Bulk administration
commands (`import`, `transfer`, `migrate`) are CLI-only.

## Testing the library locally

To test the library locally, you can install the built package with
`pip install dist/environment_store-0.1.0-py3-none-any.whl` in a different virtual environment.

### Running the CLI or TUI from a clone

Run the tools straight from a cloned repository, without installing anything, using `uvx` and the
path to the clone. Add `--refresh` to pick up local changes if uv reuses a cached build:

```bash
# CLI
uvx --from "environment-store[full] @ path/to/repo" environment-store \
  --backend json --json-file ./store.json list -o acme

# TUI
uvx --from "environment-store[full] @ path/to/repo" environment-store \
  --backend json --json-file ./store.json tui
```

Use `[aws]`, `[postgres]` or `[tui]` instead of `[full]` to install only what you need. Inside the clone itself,
`uv run environment-store ...` does the same using the project environment.
