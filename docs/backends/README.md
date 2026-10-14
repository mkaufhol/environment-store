# Storage backends

A backend (an *adapter* in code) decides where variables are stored. The manager API, the [CLI](../cli.md) and the
[TUI](../tui.md) behave the same for all of them.

| Backend | CLI `--backend` | Extra | Good for |
|---|---|---|---|
| [JSON file](json-file.md) | `json` | _(none)_ | local development, tests, small setups |
| [PostgreSQL](postgresql.md) | `postgres` | `postgres` | a shared store in your own database |
| [AWS Parameter Store](aws-parameter-store.md) | `ssm` | `aws` | AWS workloads, one parameter per variable |
| [AWS Secrets Manager](aws-secrets-manager.md) | `secretsmanager` | `aws` | AWS workloads, one secret per level |

Move between backends at any time with [`transfer`](../cli.md#transferring-a-store-between-backends).

Names (organisation, project, environment, service and variable names) are plain strings. The AWS backends only
allow `a-zA-Z0-9_.-` and reject everything else with a `ValueError`; PostgreSQL limits each name to 100 characters.
If you may switch backends later, stick to the AWS character set.

## AWS backends

Both AWS backends need the `aws` extra. The connection works exactly like boto3: environment variables,
`~/.aws/credentials`, SSO or instance roles. See the
[boto3 configuration guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration).
You must pass a region (`region="eu-central-1"`, `--region`, `ENVIRONMENT_STORE_REGION` or `AWS_REGION`).

Use a `prefix` to keep several stores in one account apart (for example one per application).

## Adding another backend

Follow the guide [Adding a storage adapter](../adding-an-adapter.md).
