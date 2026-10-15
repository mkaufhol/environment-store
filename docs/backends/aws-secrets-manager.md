## AWS Secrets Manager

Needs the `aws` extra. The connection works exactly like boto3 (see the [AWS notes](README.md#aws-backends)).

The whole store is **one secret** named `<prefix>` (default `environment-store`). It holds a flat JSON object whose
keys are the variable paths `organisation/project/environment/service/NAME` (root level variables are just `NAME`):

```
myapp   ->   {
  "LOG_LEVEL": "info",
  "acme/SENTRY_DSN": "...",
  "acme/webapp/dev/api/DB_HOST": "...",
  "acme/webapp/dev/api/DB_PORT": "..."
}
```

Secrets Manager bills per secret, so one secret per store is the cheapest layout. Use a different prefix for every
store you want to keep apart (for example `myapp/prod` and `myapp/staging`); a prefix containing `/` is simply the
name of the secret.

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

- Updates are **read-modify-write** on the single secret. Two writers changing the store at the same time can
  overwrite each other, even on different levels (last write wins).
- The whole store must fit into one secret value: Secrets Manager allows **64 KiB** (65536 bytes) of JSON. A write
  that would exceed it fails with a `ValueError` and leaves the secret unchanged; split the store across prefixes.
- The secret is **deleted without a recovery window** once the store's last variable is deleted.
- IAM policies can only grant access to a whole store (one secret), not to individual levels.
- IAM permissions used: `secretsmanager:GetSecretValue`, `PutSecretValue`, `CreateSecret`, `DeleteSecret` and
  `ListSecrets`, plus KMS permissions for a customer-managed key.

## Parameter Store or Secrets Manager

| | Parameter Store | Secrets Manager |
|---|---|---|
| Granularity | one parameter per variable | one secret per store (prefix) |
| Cost model | standard parameters are free of charge | billed per secret, so fewer secrets are cheaper |
| Concurrent writes | independent per variable | last write wins per store |
| Size limit | 4 KiB per standard parameter | 64 KiB for the whole store |
| Per-variable IAM | possible (by path) | per store only |

Check the current AWS pricing and quotas before deciding.

[Back to the storage backends overview](README.md)
