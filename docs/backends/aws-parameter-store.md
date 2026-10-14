## AWS Parameter Store

Needs the `aws` extra. The connection works exactly like boto3 (see the [AWS notes](README.md#aws-backends)).

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

## CLI and TUI

Select this backend with `--backend ssm` plus the options below. They go **before** the command (or `tui`),
or can be set as environment variables so you do not repeat them.

| Option | Environment variable | Required |
|---|---|---|
| `--backend ssm` | `ENVIRONMENT_STORE_BACKEND=ssm` | yes |
| `--region REGION` | `ENVIRONMENT_STORE_REGION` or `AWS_REGION` | yes |
| `--prefix PREFIX` | `ENVIRONMENT_STORE_PREFIX` | no, default none (parameters at `/<NAME>`) |
| `--parameter-type TYPE` | `ENVIRONMENT_STORE_PARAMETER_TYPE` | no, `SecureString` (default) or `String` |

```bash
# CLI
environment-store --backend ssm --region eu-central-1 --prefix myapp list -o acme

# TUI
environment-store --backend ssm --region eu-central-1 --prefix myapp tui

# the same with environment variables
export ENVIRONMENT_STORE_BACKEND=ssm ENVIRONMENT_STORE_REGION=eu-central-1 ENVIRONMENT_STORE_PREFIX=myapp
environment-store list -o acme
environment-store tui
```

As the destination of [`transfer`](../cli.md#transferring-a-store-between-backends) use the `--dest-` variant of
each option (`ENVIRONMENT_STORE_DEST_*`):

```bash
environment-store --backend json --json-file ./store.json transfer \
  --dest-backend ssm --dest-region eu-central-1 --dest-prefix myapp --dry-run
```

AWS credentials come from the boto3 chain (environment variables, `~/.aws/credentials`, SSO, instance roles); there is no credential option.

IAM permissions used: `ssm:GetParameter`, `ssm:GetParametersByPath`, `ssm:PutParameter`, `ssm:DeleteParameter`,
`ssm:DeleteParameters`, plus `kms:Decrypt` and `kms:Encrypt` on the key if you use a customer-managed KMS key for
`SecureString`. Restrict the policy to `arn:aws:ssm:<region>:<account>:parameter/<prefix>/*`.

The underlying `ParameterStore` class (`environment_store.adapters.aws.ssm_parameter_store.ParameterStore`) is a thin
wrapper around the boto3 SSM client and can be used on its own.

Compare with [Secrets Manager](aws-secrets-manager.md#parameter-store-or-secrets-manager).

[Back to the storage backends overview](README.md)
