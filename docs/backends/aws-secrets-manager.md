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

```bash
environment-store --backend secretsmanager --region eu-central-1 --prefix myapp list
```

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
