# JSON file

Stores everything in one local JSON file. It is created on the first write.

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

manager = EnvironmentStoreManager(adapter=JsonFileAdapter("./store.json"))
```

## CLI and TUI

Select this backend with `--backend json` plus the options below. They go **before** the command (or `tui`),
or can be set as environment variables so you do not repeat them.

| Option | Environment variable | Required |
|---|---|---|
| `--backend json` | `ENVIRONMENT_STORE_BACKEND=json` | yes |
| `--json-file PATH` | `ENVIRONMENT_STORE_JSON_FILE` | yes (file is created on first write) |

```bash
# CLI
environment-store --backend json --json-file ./store.json list -o acme

# TUI
environment-store --backend json --json-file ./store.json tui

# the same with environment variables
export ENVIRONMENT_STORE_BACKEND=json ENVIRONMENT_STORE_JSON_FILE=./store.json
environment-store list -o acme
environment-store tui
```

As the destination of [`transfer`](../cli.md#transferring-a-store-between-backends) use the `--dest-` variant of
each option (`ENVIRONMENT_STORE_DEST_*`):

```bash
environment-store --backend json --json-file ./a.json transfer \
  --dest-backend json --dest-json-file ./b.json --dry-run
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
