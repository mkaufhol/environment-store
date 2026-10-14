# Using environment-store from Python

Everything goes through `EnvironmentStoreManager`. It works the same for every
[storage backend](backends.md); only the adapter you pass in differs.

- [Create a manager](#create-a-manager)
- [The hierarchy](#the-hierarchy)
- [Writing variables](#writing-variables)
- [Reading variables](#reading-variables)
- [Resolved variables (with parent levels)](#resolved-variables-with-parent-levels)
- [Discovering levels](#discovering-levels)
- [Deleting](#deleting)
- [Copying between stores](#copying-between-stores)
- [Errors](#errors)
- [Writing your own adapter](#writing-your-own-adapter)

## Create a manager

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

manager = EnvironmentStoreManager(adapter=JsonFileAdapter("./store.json"))
```

Other adapters (see [Storage backends](backends.md) for their options):

```python
from environment_store.adapters.postgresql import PostgreSQLAdapter
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter
from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

PostgreSQLAdapter("postgresql+psycopg://user:password@localhost/environment_store")
ParameterStoreAdapter(region="eu-central-1", prefix="myapp")
SecretsManagerAdapter(region="eu-central-1", prefix="myapp")
```

## The hierarchy

Variables live at a level: `organisation > project > environment > service`. Every method that works on a level takes
the keyword arguments `organisation`, `project`, `environment` and `service`. They are all optional:

| You pass | Level |
|---|---|
| nothing | root |
| `organisation="acme"` | the organisation |
| `organisation="acme", project="webapp"` | the project |
| `organisation=..., project=..., environment=..., service=...` | the service |

Rules:

- **No skipping.** A `service` needs an `environment`, an `environment` needs a `project`, a `project` needs an
  `organisation`, otherwise a `ValueError` is raised.
- **Pass the hierarchy as keyword arguments.** The validation only sees keyword arguments, so
  `manager.set_variable("A", "1", None, "web")` would skip the check. Always write `project="web"`.
- Variable names are unique within a level, not across levels.
- A level exists as long as it holds variables; there is no separate "create level" call. Setting a variable
  under `organisation="new"` creates the organisation.
- AWS backends restrict names to `a-zA-Z0-9_.-`.

## Writing variables

```python
manager.set_variable("DB_HOST", "localhost", organisation="acme", project="webapp")

# several at once, from a dict or a list of Variable objects
manager.set_variables({"LOG_LEVEL": "INFO", "PORT": "8080"}, organisation="acme")

from environment_store.core.schemas import Variable

manager.set_variables([Variable(name="A", value="1")], organisation="acme")
```

`set_variable` creates the variable or overwrites its value. Values are always strings.

## Reading variables

```python
manager.get_variable("DB_HOST", organisation="acme", project="webapp")  # -> "localhost" or None

manager.get_variables(organisation="acme")  # -> [Variable(name=..., value=...), ...]
manager.get_variables_as_dict(organisation="acme")  # -> {"LOG_LEVEL": "INFO", "PORT": "8080"}
manager.get_root_variables()  # same as get_variables() with no arguments
```

These return the variables of **exactly that level**, nothing inherited. `get_variable` returns `None` if the variable
does not exist.

## Resolved variables (with parent levels)

The resolved variables of a level are its own plus those of every parent level, with deeper levels overriding
shallower ones:

```python
manager.get_resolved_variables(
    organisation="acme", project="webapp", environment="prod", service="api"
)
```

`get_resolved_variables` works for any level (including the root). Level-specific variants give more control:

```python
manager.get_organisation_variables("acme")
manager.get_project_variables("acme", "webapp")
manager.get_environment_variables("acme", "webapp", "prod")
manager.get_service_variables("acme", "webapp", "prod", "api")
```

All four accept:

- `include_parent=True`: set to `False` to get only the level's own variables.
- `overwrite_parent=True`: set to `False` to keep the **parent's** value when a name exists on both levels.

## Discovering levels

```python
manager.get_organisations()  # ["acme", "other"]
manager.get_projects("acme")  # ["webapp"]
manager.get_environments("acme", "webapp")  # ["dev", "prod"]
manager.get_services("acme", "webapp", "prod")  # ["api"]

# one call for any depth, always sorted; a service has no children
manager.get_child_levels()  # organisations
manager.get_child_levels(organisation="acme")  # projects of acme
```

Walk a whole store (or a subtree) level by level, parents before children. Only levels that hold variables are
yielded:

```python
for path, variables in manager.iter_levels():
    print(path, {v.name: v.value for v in variables})
# () {'LOG_LEVEL': 'info'}
# ('acme',) {'DB_HOST': '...'}
# ('acme', 'webapp') ...

manager.iter_levels(organisation="acme", project="webapp")  # only that subtree
```

`path` is a tuple such as `("acme", "webapp")`; the root is `()`.
`environment_store.core.hierarchy` has helpers for working with paths (`to_kwargs`, `to_path`, `describe`, ...).

## Deleting

```python
manager.delete_variable("DB_HOST", organisation="acme")  # -> True if it existed
manager.delete_variables(
    ["A", "B"], organisation="acme"
)  # -> {"deleted": [...], "not_found": [...]}
```

Deleting a **whole level** removes its variables and every level below it. It needs the exact name of the level as a
confirmation, so it cannot happen by accident:

```python
variables, sub_levels = manager.count_level(
    organisation="acme", project="webapp"
)  # what would go

manager.delete_level(
    organisation="acme", project="webapp", confirm="webapp"
)  # -> number of variables deleted
```

- The root cannot be deleted this way (`organisation` is required).
- `confirm` must equal the name of the deepest level you pass, otherwise `ConfirmationMismatchError` is raised and
  nothing is deleted.

## Copying between stores

Copy one store (or a subtree) into another, for example from a JSON file to PostgreSQL:

```python
source = EnvironmentStoreManager(JsonFileAdapter("./store.json"))
destination = EnvironmentStoreManager(PostgreSQLAdapter(url))

result = destination.import_from(source, dry_run=True)  # preview
result = destination.import_from(source, overwrite=False)  # copy

result.created, result.updated, result.unchanged, result.skipped
result.conflicts  # [TransferConflict(path=["acme"], name="DB_HOST"), ...]
```

- Missing variables are created, identical ones are left alone.
- Variables that exist with a different value are skipped and listed in `conflicts`, unless `overwrite=True`.
- Pass `organisation=...` etc. to copy only a subtree. The source is never modified.

## Errors

| Error | When |
|---|---|
| `ValueError` | skipped hierarchy level (`service` without `environment`), invalid names (AWS), empty variable name |
| `ConfirmationMismatchError` (a `ValueError`) | `delete_level` with the wrong `confirm` |
| `VariableExistsError`, `VariableNotFoundError` | `create_variable` / `update_variable` on adapters that implement them (PostgreSQL, Secrets Manager) |

All are importable from `environment_store.core.exceptions`. Backend failures (network, credentials, database)
surface as the underlying library's exceptions (`botocore`, `sqlalchemy`, ...).

## Writing your own adapter

Subclass `environment_store.core.abstract_adapter.AbstractAdapter` and implement its ten abstract methods:
`set_variable`, `set_variables`, `get_variable`, `get_variables`, `delete_variable`, `delete_variables`,
`get_organisations`, `get_projects`, `get_environments` and `get_services`. (`create_variable`, `update_variable`
and `variable_exists` are optional extras that some adapters offer.) The docstrings in
[`abstract_adapter.py`](../src/environment_store/core/abstract_adapter.py) describe the contract for each method.
Pass an instance to `EnvironmentStoreManager`. See [Development](development.md#adding-a-storage-adapter) for the
checklist.
