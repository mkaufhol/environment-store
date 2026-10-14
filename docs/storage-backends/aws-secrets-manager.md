# AWS Secrets Manager (`SecretsManagerAdapter`)

Stores each hierarchy level as **one** Secrets Manager secret holding a JSON object of its variables, e.g.
`myapp/acme/webapp/dev/api` -> `{"DB_HOST": "...", "DB_PORT": "..."}`. Install the `aws` extra. Credentials and
naming rules are described in the [overview](README.md#aws-backends).

The root level is the secret named `<prefix>` (default `environment-store`).

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

adapter = SecretsManagerAdapter(region="us-east-1", prefix="myapp")
manager = EnvironmentStoreManager(adapter=adapter)
```

## Caveats

- Keeps the number of billed secrets low, but updates are read-modify-write: concurrent writers on the same level
  can overwrite each other (last write wins).
- A level's secret is deleted (without recovery window) once its last variable is deleted.

## CLI / TUI

```bash
environment-store --backend secretsmanager --region us-east-1 --prefix myapp list -o acme
```

| Option | Environment variable |
|--------|----------------------|
| `--region` | `ENVIRONMENT_STORE_REGION`, `AWS_REGION` |
| `--prefix` | `ENVIRONMENT_STORE_PREFIX` |

[Back to the overview](README.md)
