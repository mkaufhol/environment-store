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
| `postgres` | `PostgreSQLAdapter` (psycopg, sqlalchemy)              |
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
| `↑` `↓`  | move; selecting a tree node shows that level's variables            |
| `→` `←`  | expand / collapse a tree node                                       |
| `a`      | add a variable at the selected level                                |
| `e`      | edit the highlighted variable                                       |
| `d`      | delete the highlighted variable (asks for confirmation)             |
| `n`      | new child level (organisation at root, then project, environment, service); asks for a name and a first variable, since a level exists once it holds a variable |
| `r`      | toggle the resolved view (merged with parent levels, deeper wins)   |
| `v`      | show / hide values                                                  |
| `F5`     | reload the tree and the table                                       |
| `q`      | quit                                                                |

In the resolved view the table is read-only; switch it off with `r` to edit or delete.

## EnvironmentStoreManager usage

### Initialization

To initialize the `EnvironmentStoreManager` you need to provide an adapter that implements the `AbstractAdapter` interface.
The available adapters are described in the [storage backends overview](docs/storage-backends/README.md).

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
```

An agent skill describing efficient CLI usage lives in
[.claude/skills/environment-store-cli/SKILL.md](.claude/skills/environment-store-cli/SKILL.md).

---

# Storage backends

Variables can be stored in a local JSON file, a PostgreSQL database, AWS Parameter Store or AWS Secrets Manager.
See the [storage backends overview](docs/storage-backends/README.md) for a comparison and the setup of each backend.

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
