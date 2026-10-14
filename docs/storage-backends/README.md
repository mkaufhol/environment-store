# Storage backends

The `EnvironmentStoreManager` stores its variables through an adapter implementing the `AbstractAdapter`
interface. Pick the backend that fits where your variables should live.

| Backend | Adapter | CLI `--backend` | Extra | Stores variables in |
|---------|---------|-----------------|-------|---------------------|
| [Local JSON file](json-file.md) | `JsonFileAdapter` | `json` | _(none)_ | one local JSON file |
| [PostgreSQL](postgresql.md) | `PostgreSQLAdapter` | `postgres` | `postgres` | one table in a PostgreSQL 15+ database |
| [AWS Parameter Store](aws-parameter-store.md) | `ParameterStoreAdapter` | `ssm` | `aws` | one SSM parameter per variable |
| [AWS Secrets Manager](aws-secrets-manager.md) | `SecretsManagerAdapter` | `secretsmanager` | `aws` | one secret (JSON object) per hierarchy level |

See the [README](../../README.md#installation) for how to install the extras.

## Using an adapter

Create the adapter and hand it to the manager:

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

manager = EnvironmentStoreManager(adapter=JsonFileAdapter("path/to/file.json"))
```

The CLI and the terminal UI select the backend with `--backend` (or `ENVIRONMENT_STORE_BACKEND`). The options of
each backend are listed on its page; run `environment-store --help` for all of them.

## AWS backends

Both AWS backends need the `aws` extra and connect like boto3 does (environment variables, shared credentials
file, instance roles, ...), see the
[boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration).
Names (organisation, project, environment, service, variable and prefix segments) may only contain `a-zA-Z0-9_.-`.
