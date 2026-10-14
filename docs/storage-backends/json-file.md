# Local JSON file (`JsonFileAdapter`)

Stores the environment variables in a local JSON file. It is useful for testing and development purposes.
It needs no extra: it is part of the core package.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

adapter = JsonFileAdapter("path/to/file.json")
manager = EnvironmentStoreManager(adapter=adapter)
```

## CLI / TUI

```bash
environment-store --backend json --json-file ./store.json list -o acme
```

| Option | Environment variable |
|--------|----------------------|
| `--json-file PATH` | `ENVIRONMENT_STORE_JSON_FILE` |

[Back to the overview](README.md)
