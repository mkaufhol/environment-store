# AWS Parameter Store (`ParameterStoreAdapter`)

Stores every variable as one AWS Systems Manager Parameter Store parameter. Install the `aws` extra. Credentials
and naming rules are described in the [overview](README.md#aws-backends).

The hierarchy is the parameter path:
`/<prefix>/<organisation>/<project>/<environment>/<service>/<NAME>` (root variables live at `/<NAME>`).
Values are written as `SecureString` by default (`parameter_type="String"` to change that).

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.aws.ssm_parameter_store import ParameterStoreAdapter

adapter = ParameterStoreAdapter(region="us-east-1", prefix="myapp")
manager = EnvironmentStoreManager(adapter=adapter)
```

The underlying `ParameterStore` class is a simple wrapper around the boto3 ssm client and can also be used standalone.

## CLI / TUI

```bash
environment-store --backend ssm --region us-east-1 --prefix myapp list -o acme
```

| Option | Environment variable |
|--------|----------------------|
| `--region` | `ENVIRONMENT_STORE_REGION`, `AWS_REGION` |
| `--prefix` | `ENVIRONMENT_STORE_PREFIX` |
| `--parameter-type` | `ENVIRONMENT_STORE_PARAMETER_TYPE` |

[Back to the overview](README.md)
