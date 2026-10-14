# JSON file

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

[Back to the storage backends overview](README.md)
