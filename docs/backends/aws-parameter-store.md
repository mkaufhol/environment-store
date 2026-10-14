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

```bash
environment-store --backend ssm --region eu-central-1 --prefix myapp --parameter-type SecureString list
```

IAM permissions used: `ssm:GetParameter`, `ssm:GetParametersByPath`, `ssm:PutParameter`, `ssm:DeleteParameter`,
`ssm:DeleteParameters`, plus `kms:Decrypt` and `kms:Encrypt` on the key if you use a customer-managed KMS key for
`SecureString`. Restrict the policy to `arn:aws:ssm:<region>:<account>:parameter/<prefix>/*`.

The underlying `ParameterStore` class (`environment_store.adapters.aws.ssm_parameter_store.ParameterStore`) is a thin
wrapper around the boto3 SSM client and can be used on its own.

Compare with [Secrets Manager](aws-secrets-manager.md#parameter-store-or-secrets-manager).

[Back to the storage backends overview](README.md)
