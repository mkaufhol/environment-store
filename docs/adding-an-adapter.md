# Adding a storage adapter

A step-by-step guide to adding a new storage backend (an *adapter*) to environment-store: from the class itself
to the CLI, TUI, packaging, tests and docs. For the bigger picture read the
[architecture section](development.md#architecture-one-shared-layer) first.

- [How adapters fit in](#how-adapters-fit-in)
- [Checklist](#checklist)
- [1. Understand the contract](#1-understand-the-contract)
- [2. Write the adapter (worked example)](#2-write-the-adapter-worked-example)
- [3. Design decisions every backend has to make](#3-design-decisions-every-backend-has-to-make)
- [4. Test it with the shared contract](#4-test-it-with-the-shared-contract)
- [5. Packaging: extras and lazy imports](#5-packaging-extras-and-lazy-imports)
- [6. Wire it into the CLI](#6-wire-it-into-the-cli)
- [7. Document it](#7-document-it)
- [Gotchas](#gotchas)

## How adapters fit in

```
CLI / TUI / API  ->  EnvironmentStoreManager  ->  AbstractAdapter  ->  your backend
```

The manager adds hierarchy validation and all the higher-level behaviour (resolved variables, level deletion,
transfers). **An adapter only has to store and retrieve variables at a level.** Because every frontend sits on the
manager, a correct adapter automatically works in the Python API, the CLI (including `transfer`) and the TUI.
You do not touch `manager.py`, `tui/app.py` or any command implementation.

## Checklist

- [ ] Adapter class in `src/environment_store/adapters/<name>/` implementing the ten abstract methods
- [ ] Hierarchy and name validation, with `ValueError`s as the contract describes
- [ ] A level disappears when its last variable is deleted
- [ ] Package `__init__.py` exports the adapter
- [ ] Optional extra in `pyproject.toml` **and** added to `full`; third-party imports are lazy
- [ ] Tests: shared contract suite plus backend-specific tests
- [ ] CLI: `BACKENDS`, options, `build_manager`, `_backend_identity`
- [ ] Docs: [backends/](backends/README.md), [installation.md](installation.md), [cli.md](cli.md), the agent skill
- [ ] `uv run pytest`, `uv run ruff check`, `uv run ty check` pass

## 1. Understand the contract

Subclass `environment_store.core.abstract_adapter.AbstractAdapter`. The module docstring and the method docstrings
in [`abstract_adapter.py`](../src/environment_store/core/abstract_adapter.py) are the specification. In short:

| Method | Must do |
|---|---|
| `set_variable(name, value, organisation, project, environment, service)` | upsert one variable at exactly that level |
| `set_variables(variables, ...)` | upsert many; an empty list is a no-op |
| `get_variable(name, ...)` | the value, or `None` if missing. **Exact level only**, never parents |
| `get_variables(...)` | `list[Variable]` of exactly that level; `[]` if none; never child levels |
| `delete_variable(name, ...)` | `True` if it existed and was deleted, else `False` |
| `delete_variables(names, ...)` | `{"deleted": [...], "not_found": [...]}`; an empty list raises `ValueError` |
| `get_organisations()` | unique names |
| `get_projects(organisation)` | unique names, `[]` if the organisation does not exist |
| `get_environments(organisation, project)` | same |
| `get_services(organisation, project, environment)` | same |

All hierarchy parameters are optional and default to `None`; all `None` means the **root** level.

Behaviour that the rest of the project relies on:

- **Levels are implicit.** There is no "create level" operation. A level exists as long as it, or something below it,
  holds a variable. `get_organisations()` must therefore include an organisation whose variables only live in a
  project below it.
- **Deleting the last variable removes the level.** The TUI tree, `delete_level` and `transfer` all depend on empty
  levels not lingering.
- **Errors.** Raise `ValueError` for an empty or (for your backend) invalid name, and for a skipped hierarchy level
  (for example `service` without `environment`). Backend failures (network, auth) should surface as the underlying
  library's exceptions.
- **Values are strings** and must round-trip exactly (newlines, unicode, quotes, padding).
- **Order is not guaranteed** by the contract. The manager sorts where it matters (`get_child_levels`).
- `create_variable`, `update_variable` and `variable_exists` are **optional extras**. Implement them if your backend
  can do so atomically; they raise `VariableExistsError` / `VariableNotFoundError` (from `core.exceptions`).

## 2. Write the adapter (worked example)

This complete adapter keeps variables in memory. It is useful as a test double and shows the shape of every real
adapter. Real backends replace the `dict` with calls to their storage; the validation and the "levels are
derived from what is stored" idea stay the same.

```python
from environment_store.core.abstract_adapter import AbstractAdapter
from environment_store.core.hierarchy import Path, to_path
from environment_store.core.schemas import Variable


class MemoryAdapter(AbstractAdapter):
    """Keeps all variables in a dict, keyed by the path of the level they belong to."""

    def __init__(self) -> None:
        self._levels: dict[Path, dict[str, str]] = {}

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _path(organisation, project, environment, service) -> Path:
        """Validate the hierarchy rules and turn the arguments into a path (root is ``()``)."""
        given = (organisation, project, environment, service)
        path = to_path(*given)
        if given[: len(path)] != path:
            raise ValueError(
                "Hierarchy levels cannot be skipped: "
                "organisation > project > environment > service"
            )
        return path

    @staticmethod
    def _check_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Variable name must be a non-empty string")

    def _child_names(self, prefix: Path) -> list[str]:
        """Names of the levels directly below ``prefix``, derived from the stored paths."""
        depth = len(prefix)
        return sorted(
            {
                path[depth]
                for path in self._levels
                if len(path) > depth and path[:depth] == prefix
            }
        )

    # --- writing -----------------------------------------------------------
    def set_variable(
        self, name, value, organisation=None, project=None, environment=None, service=None
    ) -> None:
        self._check_name(name)
        path = self._path(organisation, project, environment, service)
        self._levels.setdefault(path, {})[name] = value

    def set_variables(
        self, variables, organisation=None, project=None, environment=None, service=None
    ) -> None:
        for variable in variables:
            self.set_variable(
                variable.name, variable.value, organisation, project, environment, service
            )

    # --- reading -----------------------------------------------------------
    def get_variable(
        self, name, organisation=None, project=None, environment=None, service=None
    ):
        self._check_name(name)
        path = self._path(organisation, project, environment, service)
        return self._levels.get(path, {}).get(name)

    def get_variables(
        self, organisation=None, project=None, environment=None, service=None
    ) -> list[Variable]:
        path = self._path(organisation, project, environment, service)
        return [Variable(name=n, value=v) for n, v in self._levels.get(path, {}).items()]

    # --- deleting ----------------------------------------------------------
    def delete_variable(
        self, name, organisation=None, project=None, environment=None, service=None
    ) -> bool:
        self._check_name(name)
        path = self._path(organisation, project, environment, service)
        variables = self._levels.get(path, {})
        if name not in variables:
            return False
        del variables[name]
        if not variables:
            del self._levels[path]  # a level without variables no longer exists
        return True

    def delete_variables(
        self, names, organisation=None, project=None, environment=None, service=None
    ) -> dict[str, list[str]]:
        if not names:
            raise ValueError("names must not be empty")
        result: dict[str, list[str]] = {"deleted": [], "not_found": []}
        for name in names:
            deleted = self.delete_variable(name, organisation, project, environment, service)
            result["deleted" if deleted else "not_found"].append(name)
        return result

    # --- discovering levels ------------------------------------------------
    def get_organisations(self) -> list[str]:
        return self._child_names(())

    def get_projects(self, organisation: str) -> list[str]:
        return self._child_names((organisation,))

    def get_environments(self, organisation: str, project: str) -> list[str]:
        return self._child_names((organisation, project))

    def get_services(self, organisation: str, project: str, environment: str) -> list[str]:
        return self._child_names((organisation, project, environment))
```

Use it exactly like any other adapter:

```python
from environment_store import EnvironmentStoreManager

manager = EnvironmentStoreManager(adapter=MemoryAdapter())
manager.set_variable("DB_HOST", "localhost", organisation="acme", project="webapp")
manager.get_child_levels(organisation="acme")  # ["webapp"]
```

Look at the real adapters for patterns with a real backend:

| Adapter | Read it for |
|---|---|
| [`json_file_adapter.py`](../src/environment_store/adapters/json/json_file_adapter.py) | the simplest persistent adapter (load, change, save a file) |
| [`postgresql_adapter.py`](../src/environment_store/adapters/postgresql/postgresql_adapter.py) | SQL, transactions, migrations, accepting an existing engine |
| [`ssm_parameter_store/adapter.py`](../src/environment_store/adapters/aws/ssm_parameter_store/adapter.py) | mapping the hierarchy to key paths, pagination, name validation |
| [`secrets_manager/adapter.py`](../src/environment_store/adapters/aws/secrets_manager/adapter.py) | one document per level, read-modify-write, deleting empty levels |

Both AWS adapters take the low-level client wrapper as an optional constructor argument
(`parameter_store=`, `secrets_manager=`). Do the same for your backend: injecting the client makes the adapter easy
to test with a fake.

## 3. Design decisions every backend has to make

Decide and document these before you write much code:

1. **How is the hierarchy encoded?** A key path (`/prefix/org/project/env/service/NAME`), columns (PostgreSQL), nested
   documents (JSON), one document per level (Secrets Manager). Pick the encoding that lets you list the children of a
   level cheaply, because `get_projects` and friends need that.
2. **What are the allowed characters and lengths?** Reject what the backend cannot store with a `ValueError` and a
   message that names the allowed characters. Validate **every** name that ends up in a key: organisation, project,
   environment, service, variable and any configured prefix. Backends stricter than others cause problems when users
   [`transfer`](cli.md#transferring-a-store-between-backends) between them, so document your limits in
   [backends/](backends/README.md).
3. **Is a prefix or namespace needed?** If the backend is shared with other data (an AWS account, a bucket), accept
   an optional `prefix` and ignore everything outside it, so several stores and unrelated entries can coexist.
4. **How do empty levels disappear?** Either derive levels from stored variables (SQL `SELECT DISTINCT`, key
   listing), or clean up containers when the last variable is deleted (JSON, Secrets Manager).
5. **Concurrency.** Say in the docs what happens with simultaneous writers. Last-write-wins is acceptable, but say so
   (see the Secrets Manager notes).
6. **Secrets.** Prefer encrypted storage where the backend offers it, and never log values.
7. **Pagination and batching.** Listing must return **all** variables, not just the first page (the contract suite
   writes 25 variables to catch this). Use the backend's batch operations in `set_variables` and
   `delete_variables` where they exist.
8. **Setup.** If the backend needs a schema or a bucket, provide a function (and a CLI command like `migrate`) and
   document it. Keep the adapter constructor free of side effects such as creating tables.

## 4. Test it with the shared contract

[`tests/environment_store/adapters/contract.py`](../tests/environment_store/adapters/contract.py) contains the
behavioural tests that **every** adapter has to pass. Subclass it, provide an `adapter` fixture that yields a fresh,
empty adapter, and you get the whole suite for free:

```python
# tests/environment_store/adapters/<name>/test_<name>_adapter.py
import pytest

from environment_store.adapters.<name> import MyAdapter
from tests.environment_store.adapters.contract import AdapterContract, StrictCreateUpdateContract


@pytest.fixture
def adapter():
    return MyAdapter(...)          # a fresh, empty store for every test


class TestMyAdapterContract(AdapterContract):          # add StrictCreateUpdateContract if you implement
    """Shared behaviour, see docs/adding-an-adapter.md."""   # create_variable, update_variable, variable_exists
```

The contract covers: round trips at every level, exact-level reads, upserts, missing values, batch writes (including
empty and more than 25 variables), deletes (single, batch, missing, siblings and same names elsewhere untouched),
hierarchy listing including implicit levels, levels disappearing after the last delete, name and hierarchy
validation, values that must round-trip exactly, and a pass through the manager (resolved variables and
`delete_level`).

Then add tests for what is specific to your backend (layout, prefix handling, error mapping), as the existing
adapters do. Practical tips:

- **Never hit a real service in the default test run.** Use a fake or an emulator (the AWS adapters use
  [moto](https://docs.getmoto.org/)). If a real service is the only option, skip the tests unless an environment
  variable is set, like the PostgreSQL tests do with `ENVIRONMENT_STORE_TEST_POSTGRES_URL`, and make the fixture start
  every test from an empty store.
- Add the test-only dependencies to the `testing` group in `pyproject.toml` and to the `deps` in `tox.ini`.
- Run just your tests while developing: `uv run pytest tests/environment_store/adapters/<name> -q`.

## 5. Packaging: extras and lazy imports

If your adapter needs third-party packages:

1. Add an optional extra in `pyproject.toml`, and add the same packages to the `full` extra:

   ```toml
   [project.optional-dependencies]
   myservice = ["myservice-sdk>=1.2"]
   full = [
       # ... existing entries ...
       "myservice-sdk>=1.2",
   ]
   ```

2. Run `uv lock` so `uv.lock` is updated (pre-commit checks this).
3. **Import the package lazily.** `import environment_store` must work without any extra installed. Only the adapter
   module imports the SDK, and nothing in `core/`, `cli.py` or the package `__init__.py` imports your adapter at
   module level. In the CLI the adapter is imported inside its `build_manager` branch (next section), which is why a
   missing extra produces the friendly "install the matching extra" message.
4. Export the class from the adapter package:

   ```python
   # src/environment_store/adapters/<name>/__init__.py
   from .adapter import MyAdapter

   __all__ = ["MyAdapter"]
   ```

## 6. Wire it into the CLI

Everything backend-specific in the CLI is in `src/environment_store/cli.py`. A new backend needs four small
changes; afterwards `transfer`, `list`, `tui` and every other command work with it, as source and as destination.

1. **Register the name:** add it to `BACKENDS`.

   ```python
   BACKENDS = ("json", "postgres", "ssm", "secretsmanager", "myservice")
   ```

2. **Add its options** in `_add_backend_options`. This one function defines the options for both the main store
   (`--endpoint`) and the destination of `transfer` (`--dest-endpoint`), so you add each option once:

   ```python
   group.add_argument(
       f"{flag}endpoint",
       dest=f"{key}endpoint",
       default=_env(f"{env}ENDPOINT"),
       help=f"myservice backend: endpoint URL ({var}ENDPOINT)",
   )
   ```

   Reuse existing options (`--region`, `--prefix`, `--database-url`) when they mean the same thing.

3. **Build the adapter** in `build_manager`, with a lazy import and a clear error for a missing option. The
   `prefix` argument lets the same code create the destination manager:

   ```python
   if backend == "myservice":
       from environment_store.adapters.myservice import MyAdapter

       endpoint = getattr(args, f"{prefix}endpoint")
       if not endpoint:
           raise CliError(f"The myservice backend needs {flag}endpoint or {env}ENDPOINT.")
       return EnvironmentStoreManager(adapter=MyAdapter(endpoint))
   ```

4. **Say what identifies a store** in `_backend_identity`, so `transfer` can refuse to copy a store onto itself:

   ```python
   if backend == "myservice":
       return (backend, getattr(args, f"{prefix}endpoint"))
   ```

Add a CLI test next to the existing ones in `tests/environment_store/test_cli.py`: run `main([...])` with your
backend options against a fake, and check `set`, `list` and a `transfer` to or from the JSON backend.

If the backend needs one-time setup (like PostgreSQL's migrations), add a command for it following `cmd_migrate`, and
document it. Such bulk administration commands are CLI-only.

## 7. Document it

- [backends/](backends/README.md): a section with the Python example, the CLI example, the storage layout, the allowed
  characters and limits, required permissions, concurrency behaviour and any setup step. Add a row to the overview
  table.
- [installation.md](installation.md) and the extras table in the [README](../README.md): the new extra, and that
  `full` includes it.
- [cli.md](cli.md#choosing-a-backend): the new options and environment variables in the backend table.
- [`.claude/skills/environment-store-cli/SKILL.md`](../.claude/skills/environment-store-cli/SKILL.md): the backend
  table, so agents know how to select it.

## Gotchas

- **Do not validate the hierarchy only in the manager.** The manager checks keyword arguments, but the adapter may be
  called directly. Validate in the adapter too (the contract tests require it).
- **Exact level means exact level.** `get_variables(organisation="acme")` must not include variables of
  `acme / webapp`. It is easy to get wrong with prefix queries (`LIKE 'acme%'`, key listings with recursion).
- **Do not return levels that only exist because of leftovers**, such as an empty JSON object or an empty secret.
  `delete_level` and the TUI would show ghosts.
- **Mind prefix collisions.** With a prefix `app`, entries under `app-other/` must not be treated as part of the store.
- **Pagination.** Many backends return 10 to 100 items per call. Loop until the listing is exhausted.
- **Do not mutate state in the constructor.** Constructing an adapter must be cheap and side-effect free, because
  the CLI builds one for every command.
- **Keep secrets out of logs and error messages.** Include names and levels in errors, never values.
