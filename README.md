# Environment store

### STATUS: WIP

This library provides a simple interface to manage environment variables on different cloud providers and also locally.
It provides a high level `EnvironmentStoreManager` class that can be used to store and retrieve hierarchical
environment variables.

## Hierarchical variables

You can organise your variables in a hierarchical structure:
Organization > Project > Environment > Service > Variable

Each level can have a set of variables. Variables are unique within a level, but not across levels.

```
Org_1
├── Project_1
│   ├── Environment_1
│   │   ├── Service_1
│   │   │   ├── Variable_1
│   │   │   └── Variable_2
│   │   └── Service_2
│   │       ├── Variable_3
│   │       └── Variable_4
│   └── Environment_2
│       ├── Service_3
│       │   ├── Variable_5
│       │   └── Variable_6
│       └── Service_4
│           ├── Variable_7
│           └── Variable_8
└── Project_2
    ├── Environment_3
    │   ├── Service_5
    │   │   ├── Variable_9
    │   │   └── Variable_10
    │   └── Service_6
    │       ├── Variable_11
    │       └── Variable_12
    └── Environment_4
        ├── Service_7
        │   ├── Variable_13
        │   └── Variable_14
        └── Service_8
            ├── Variable_15
            └── Variable_16
```

Alternatively you can also use this library without the hierarchical structure:

```
├── Variable_1
├── Variable_2
├── Variable_3
├── Variable_4
├── Variable_5
├── Variable_6
├── Variable_7
├── Variable_8
├── Variable_9
├── Variable_10
├── Variable_11
├── Variable_12
├── Variable_13
├── Variable_14
├── Variable_15
└── Variable_16
```

## EnvironmentStoreManager usage

### Initialization

To initialize the `EnvironmentStoreManager` you need to provide an adapter that implements the `AbstractAdapter` interface.
The current implemented adapters are listed in the next section.

```python
from environment_store.storages.aws_ssm_parameter_store import ParameterStoreAdapter
from environment_store.environment_store_manager import EnvironmentStoreManager

adapter = ParameterStoreAdapter(region="us-east-1")
manager = EnvironmentStoreManager(adapter=adapter)
```

### STATUS: WIP

---

# Local file storage

### STATUS: NOT IMPLEMENTED YET

# Cloud providers

## AWS

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
This project uses pre-commit for code quality checks. To install the pre-commit hooks, run `pre-commit install`.
