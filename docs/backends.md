# Storage backends

A backend (an *adapter* in code) decides where variables are stored. The manager API, the [CLI](cli.md) and the
[TUI](tui.md) behave the same for all of them.

| Backend | CLI `--backend` | Extra | Good for |
|---|---|---|---|
| [JSON file](#json-file) | `json` | _(none)_ | local development, tests, small setups |
| [PostgreSQL](#postgresql) | `postgres` | `postgres` | a shared store in your own database |
| [AWS Parameter Store](#aws-parameter-store) | `ssm` | `aws` | AWS workloads, one parameter per variable |
| [AWS Secrets Manager](#aws-secrets-manager) | `secretsmanager` | `aws` | AWS workloads, one secret per level |

Move between backends at any time with [`transfer`](cli.md#transferring-a-store-between-backends).

Names (organisation, project, environment, service and variable names) are plain strings. The AWS backends only
allow `a-zA-Z0-9_.-` and reject everything else with a `ValueError`; PostgreSQL limits each name to 100 characters.
If you may switch backends later, stick to the AWS character set.

## JSON file

Stores everything in one local JSON file. It is created on the first write.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

manager = EnvironmentStoreManager(adapter=JsonFileAdapter("./store.json"))
```

```bash
environment-store --backend json --json-file ./store.json list
```

The file nests levels as objects; string entries are variables, object entries are child levels:

```json
{
  "LOG_LEVEL": "info",
  "acme": {
    "DB_HOST": "db.acme.internal",
    "webapp": { "prod": { "LOG_LEVEL": "warning", "api": { "PORT": "8080" } } }
  }
}
```

Notes:

- The whole file is rewritten on every change and there is no locking: use it from one process at a time.
- Values are stored in plain text. Do not commit the file if it holds secrets (add it to `.gitignore`).
- Levels that lose their last variable disappear from the file.

## PostgreSQL

Stores each variable as one row of the table `environment_store` (PostgreSQL 15 or newer). Needs the `postgres`
extra.

```python
from environment_store.adapters.postgresql import PostgreSQLAdapter

# a SQLAlchemy URL ...
adapter = PostgreSQLAdapter(
    "postgresql+psycopg://user:password@localhost:5432/environment_store"
)
# ... or an existing SQLAlchemy engine
adapter = PostgreSQLAdapter(engine)
```

```bash
export ENVIRONMENT_STORE_BACKEND=postgres
export ENVIRONMENT_STORE_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/environment_store
environment-store list
```

### Create the schema first

The database must exist, and the schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/) migrations
shipped inside the package. Apply them once, and again after upgrading the library:

```bash
environment-store migrate --status     # list pending migrations, change nothing
environment-store migrate              # apply them (safe to re-run)
```

or from Python:

```python
from environment_store.adapters.postgresql import apply_migrations, pending_migrations

pending_migrations(url)  # -> ["20260315_01_Dj4Bk-initial", ...]
apply_migrations(url)  # -> list of applied migration ids
```

Until the migrations are applied, commands fail with an error about the missing `environment_store` table.
If you work on a clone of the repository you can also use the yoyo CLI directly, see
[Development](development.md#database-migrations).

### Notes

- One row per variable: `organization`, `project`, `environment`, `service`, `var`, `var_value` plus timestamps.
  `NULL` levels mean the variable lives higher up; a unique constraint (`NULLS NOT DISTINCT`) keeps names unique
  per level, and a check constraint enforces the no-skipping rule.
- `created_at` / `updated_at` are maintained by the database.
- Values are stored in plain text columns. Use database-level encryption and access control for secrets.

## AWS

Both AWS backends need the `aws` extra. The connection works exactly like boto3: environment variables,
`~/.aws/credentials`, SSO or instance roles. See the
[boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration).
You must pass a region (`region="eu-central-1"`, `--region`, `ENVIRONMENT_STORE_REGION` or `AWS_REGION`).

Use a `prefix` to keep several stores in one account apart (for example one per application).

### AWS Parameter Store

One parameter per variable. The hierarchy is the parameter path:

```
/<prefix>/<organisation>/<project>/<environment>/<service>/<NAME>
```

Root variables live at `/<prefix>/<NAME>`, or `/<NAME>` without a prefix. Values are written as `SecureString` by
default.

```python
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

adapter = ParameterStoreAdapter(
    region="eu-central-1",
    prefix="myapp",  # optional, default ""
    parameter_type="SecureString",  # or "String"
)
```

```bash
environment-store --backend ssm --region eu-central-1 --prefix myapp --parameter-type SecureString list
```

IAM permissions used: `ssm:GetParameter`, `ssm:GetParametersByPath`, `ssm:PutParameter`, `ssm:DeleteParameter`,
`ssm:DeleteParameters`, plus `kms:Decrypt` and `kms:Encrypt` on the key if you use a customer-managed KMS key for
`SecureString`. Restrict the policy to `arn:aws:ssm:<region>:<account>:parameter/<prefix>/*`.

The underlying `ParameterStore` class (`environment_store.adapters.aws.ssm_parameter_store.ParameterStore`) is a thin
wrapper around the boto3 SSM client and can be used on its own.

### AWS Secrets Manager

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

### Choosing between the two

| | Parameter Store | Secrets Manager |
|---|---|---|
| Granularity | one parameter per variable | one secret per level |
| Cost model | standard parameters are free of charge | billed per secret, so fewer secrets are cheaper |
| Concurrent writes | independent per variable | last write wins per level |
| Per-variable IAM | possible (by path) | per level only |

Check the current AWS pricing and quotas before deciding.

## Adding another backend

Implement `AbstractAdapter`, see [Python usage](python-usage.md#writing-your-own-adapter) and
[Development](development.md#adding-a-storage-adapter).
