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

```bash
pip install environment-store            # core + JsonFileAdapter
pip install "environment-store[aws]"     # + ParameterStoreAdapter, SecretsManagerAdapter (boto3)
pip install "environment-store[postgres]"  # + PostgreSQLAdapter (psycopg, sqlalchemy)
```

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

The schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/) migrations, which you have to apply
before using the adapter. Copy `src/environment_store/adapters/postgresql/yoyo-database-example.ini` to
`yoyo-database.ini` in the same directory, point it to your database and run:

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

## Testing the library locally

To test the library locally, you can install the built package with
`pip install dist/environment_store-0.1.0-py3-none-any.whl` in a different virtual environment.
