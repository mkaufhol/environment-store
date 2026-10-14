# Quickstart

Five minutes from zero to a working store. This uses a local JSON file, so you need no cloud account or database.
When you are ready for AWS or PostgreSQL, see [Storage backends](backends/README.md).

## 1. Install

```bash
uv add "environment-store[tui]"        # library + CLI + terminal UI
# or: pip install "environment-store[tui]"
```

Not published to an index you can use? Install from the repository, see [Installation](installation.md).

## 2. The idea in one minute

Variables live at a **level** of a hierarchy. Each level can hold its own variables:

```
root                      LOG_LEVEL=info
└── acme                  (organisation)       DB_HOST=db.acme.internal
    └── webapp            (project)
        └── prod          (environment)        LOG_LEVEL=warning
            └── api       (service)            PORT=8080
```

- A level is addressed by `organisation > project > environment > service`. You cannot skip a level
  (a project needs an organisation, and so on). No level at all means the **root**.
- Names are unique within a level, not across levels.
- A level exists as long as it holds variables.
- The **resolved** variables of a level are its own plus those of all parent levels. Deeper values win:
  the resolved `LOG_LEVEL` of `acme / webapp / prod / api` is `warning`.

## 3. Use the CLI

```bash
export ENVIRONMENT_STORE_BACKEND=json
export ENVIRONMENT_STORE_JSON_FILE=./store.json

environment-store set LOG_LEVEL info                                  # root
environment-store set DB_HOST db.acme.internal -o acme                # organisation
environment-store set LOG_LEVEL warning -o acme -p webapp -e prod     # environment
environment-store set PORT 8080 -o acme -p webapp -e prod -s api      # service

environment-store children                                            # acme
environment-store children -o acme                                    # webapp
environment-store get PORT -o acme -p webapp -e prod -s api           # 8080
environment-store list -o acme -p webapp -e prod -s api --resolved    # everything the api service sees
```

Output of the last command:

```
DB_HOST=db.acme.internal
LOG_LEVEL=warning
PORT=8080
```

Export it into your shell, or write it to a `.env` file:

```bash
eval "$(environment-store list -o acme -p webapp -e prod -s api --resolved --format export)"
environment-store list -o acme -p webapp -e prod -s api --resolved > .env
```

More in the [CLI guide](cli.md).

## 4. Browse it in the terminal UI

```bash
environment-store tui
```

Move with the arrow keys or `h` `j` `k` `l`, press `v` to reveal values, `a` to add, `e` to edit, `r` for the resolved
view. See the [TUI guide](tui.md).

## 5. Use it from Python

```python
from environment_store import EnvironmentStoreManager
from environment_store.adapters.json import JsonFileAdapter

manager = EnvironmentStoreManager(adapter=JsonFileAdapter("./store.json"))

manager.set_variable("DB_HOST", "localhost", organisation="acme", project="webapp")

manager.get_variable("DB_HOST", organisation="acme", project="webapp")  # "localhost"

resolved = manager.get_resolved_variables(
    organisation="acme", project="webapp", environment="prod", service="api"
)
print({v.name: v.value for v in resolved})
```

Always pass the hierarchy as **keyword** arguments (`organisation=...`). More in the
[Python guide](python-usage.md).

## 6. Move to a real backend

Copy what you have into PostgreSQL or AWS with one command, then switch the backend options:

```bash
environment-store transfer --dest-backend ssm --dest-region eu-central-1 --dest-prefix myapp --dry-run
```

See [Transferring a store](cli.md#transferring-a-store-between-backends).

## Next steps

| I want to ... | Read |
|---|---|
| install with AWS, PostgreSQL or all extras | [Installation](installation.md) |
| understand every manager method | [Python usage](python-usage.md) |
| script the store or use it in CI | [CLI guide](cli.md) |
| use AWS Parameter Store, Secrets Manager or PostgreSQL | [Storage backends](backends/README.md) |
| work on this project | [Development](development.md) |
