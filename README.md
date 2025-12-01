# Environment store

### STATUS: WIP

This library provides a simple interface to manage environment variables on AWS. It provides a
`EnvironmentVariableManager` class that can be used to store and retrieve hierarchical environment variables from
AWS Parameter Store or AWS Secrets Manager.

## Connect to AWS

### STATUS: WIP

At its core it just wraps boto3 functions into easier to use methods to create a simpler environment variable management solutions.
So the connection with AWS is the same as for boto3: https://boto3.amazonaws.com/v1/documentation/api/latest/guide/quickstart.html#configuration

## ParameterStore

### STATUS: WIP

The `ParameterStore` class is just a simple wrapper around the parameter store functions of the boto3 ssm client.
It provides simple CRUD operations for parameter store entries. It can be used as standalone for a simpler interaction
with the parameter store or used in combination with the high level `EnvironmentVariableManager` class.

## SecretsManager

### STATUS: NOT IMPLEMENTED YET

The `SecretsManager` class is a wrapper around the boto3 secrets manager client. It is not a 100% wrapper, because it
only implements functionality needed by the `EnvironmentVariableManager` class. But if you need more functionality, you
can easily access the underlying boto3 client with the `client` attribute.

# WIP

This project is currently in early development and conception phase. Not ready to use yet.

---

# Development

### Docs WIP

This project uses Poetry for dependency management.
To install the dependencies, run `poetry install --with dev --with testing --with stubs`.
To run the tests, run `poetry run pytest`.
To run the linter, run `poetry run ruff .`.
To run the formatter, run `poetry run ruff format .`.
