## AWS Secrets Manager

Needs the `aws` extra. The connection works exactly like boto3 (see the [AWS notes](README.md#aws-backends)).

One secret **per hierarchy level**, holding a JSON object of that level's variables:

```
myapp/acme/webapp/dev/api   ->   {"DB_HOST": "...", "DB_PORT": "..."}
```

The root level is the secret named `<prefix>` (default `environment-store`). This keeps the number of billed secrets
low.

```python
from environment_store.adapters.aws.secrets_manager import SecretsManagerAdapter

adapter = SecretsManagerAdapter(region="eu-central-1", prefix="myapp")
```

## CLI and TUI

Select this backend with `--backend secretsmanager` plus the options below. They go **before** the command (or `tui`),
or can be set as environment variables so you do not repeat them.

| Option | Environment variable | Required |
|---|---|---|
| `--backend secretsmanager` | `ENVIRONMENT_STORE_BACKEND=secretsmanager` | yes |
| `--region REGION` | `ENVIRONMENT_STORE_REGION` or `AWS_REGION` | yes |
| `--prefix PREFIX` | `ENVIRONMENT_STORE_PREFIX` | no, default `environment-store` |

```bash
# CLI
environment-store --backend secretsmanager --region eu-central-1 --prefix myapp list -o acme

# TUI
environment-store --backend secretsmanager --region eu-central-1 --prefix myapp tui

# the same with environment variables
export ENVIRONMENT_STORE_BACKEND=secretsmanager ENVIRONMENT_STORE_REGION=eu-central-1 ENVIRONMENT_STORE_PREFIX=myapp
environment-store list -o acme
environment-store tui
```

As the destination of [`transfer`](../cli.md#transferring-a-store-between-backends) use the `--dest-` variant of
each option (`ENVIRONMENT_STORE_DEST_*`):

```bash
environment-store --backend json --json-file ./store.json transfer \
  --dest-backend secretsmanager --dest-region eu-central-1 --dest-prefix myapp --dry-run
```

`--parameter-type` does not apply to this backend. AWS credentials come from the boto3 chain; there is no credential option.

Things to know:

- Updates are **read-modify-write**. Two writers changing the same level at the same time can overwrite each other
  (last write wins).
- A level's secret is **deleted without a recovery window** once its last variable is deleted.
- IAM permissions used: `secretsmanager:GetSecretValue`, `PutSecretValue`, `CreateSecret`, `DeleteSecret` and
  `ListSecrets`, plus KMS permissions for a customer-managed key.

## Parameter Store or Secrets Manager

| | Parameter Store | Secrets Manager |
|---|---|---|
| Granularity | one parameter per variable | one secret per level |
| Cost model | standard parameters are free of charge | billed per secret, so fewer secrets are cheaper |
| Concurrent writes | independent per variable | last write wins per level |
| Per-variable IAM | possible (by path) | per level only |

Check the current AWS pricing and quotas before deciding.

[Back to the storage backends overview](README.md)
