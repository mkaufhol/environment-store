# Command line interface

The package installs an `environment-store` command (also available as `python -m environment_store`).
It is a thin layer over `EnvironmentStoreManager`, so everything you can do here you can do from
[Python](python-usage.md), and most of it from the [TUI](tui.md).

- [Choosing a backend](#choosing-a-backend)
- [Addressing a level](#addressing-a-level)
- [Commands](#commands)
- [Transferring a store between backends](#transferring-a-store-between-backends)
- [Output, exit codes and scripting](#output-exit-codes-and-scripting)
- [Recipes](#recipes)

## Choosing a backend

Every command needs to know which store to use. Pass options **before** the command, or set environment
variables so you do not have to repeat them:

| Option | Environment variable | Backend | Meaning |
|---|---|---|---|
| `--backend` | `ENVIRONMENT_STORE_BACKEND` | all | `json`, `postgres`, `ssm` or `secretsmanager` |
| `--json-file` | `ENVIRONMENT_STORE_JSON_FILE` | `json` | path of the JSON file (created on first write) |
| `--database-url` | `ENVIRONMENT_STORE_DATABASE_URL` | `postgres` | SQLAlchemy URL, e.g. `postgresql+psycopg://user:pw@host/db` |
| `--region` | `ENVIRONMENT_STORE_REGION` or `AWS_REGION` | `ssm`, `secretsmanager` | AWS region |
| `--prefix` | `ENVIRONMENT_STORE_PREFIX` | `ssm`, `secretsmanager` | name prefix, to keep several stores apart |
| `--parameter-type` | `ENVIRONMENT_STORE_PARAMETER_TYPE` | `ssm` | `SecureString` (default) or `String` |

```bash
# explicit
environment-store --backend json --json-file ./store.json list

# or via the environment
export ENVIRONMENT_STORE_BACKEND=json ENVIRONMENT_STORE_JSON_FILE=./store.json
environment-store list
```

AWS credentials come from the usual boto3 chain (environment variables, shared credentials file, instance roles).
Details per backend: [Storage backends](backends.md).

## Addressing a level

Commands that work on a level take the hierarchy options. Without them they work on the **root** level.

| Option | Level | Requires |
|---|---|---|
| `-o`, `--organisation` | organisation | |
| `-p`, `--project` | project | `-o` |
| `-e`, `--environment` | environment | `-p` |
| `-s`, `--service` | service | `-e` |

Skipping a level is an error (exit code 2). Names are case-sensitive.

## Commands

### `set`: create or update a variable

```bash
environment-store set DB_HOST localhost -o acme -p webapp
printf %s "$SECRET" | environment-store set API_KEY --stdin -o acme      # keeps secrets out of the process list
environment-store set TLS_CERT --from-file ./cert.pem -o acme
```

Provide exactly one of `VALUE`, `--stdin` or `--from-file`. With `--stdin` one trailing newline is removed.
Setting a variable under a level that does not exist yet creates that level.

### `get`: print one variable

```bash
environment-store get DB_HOST -o acme -p webapp          # prints the value, exit code 1 if it does not exist
environment-store get DB_HOST -o acme --format json      # {"name": "DB_HOST", "value": "..."}
environment-store get DB_HOST -o acme --raw              # no trailing newline
```

`get` reads **exactly that level**. Use `list --resolved` to include parent levels.

### `list` (alias `ls`): list variables

```bash
environment-store list -o acme -p webapp                           # NAME=value lines, that level only
environment-store list -o acme -p webapp --resolved                # merged with parent levels, deeper wins
environment-store list -o acme --format json                       # {"NAME": "value", ...}
environment-store list -o acme --names-only                        # names only
environment-store list -o acme --mask                              # values shown as ***
```

Formats (`--format`): `dotenv` (default, quotes values that need it), `export` (`export NAME='value'`, for
`eval`), `json` and `table`.

### `delete` (alias `rm`): delete variables

```bash
environment-store delete DB_HOST -o acme -p webapp --yes
environment-store delete A B C -o acme --yes
```

On a terminal it asks for confirmation unless you pass `--yes`/`-y`. Without a terminal it does not ask, so scripts
and agents must be deliberate about what they pass.

### `import`: set many variables from a file

```bash
environment-store import .env -o acme -p webapp -e dev
environment-store import vars.json -o acme --dry-run
cat .env | environment-store import - -o acme
```

Reads a `.env` file (`KEY=value`, comments, `export KEY=...`, single and double quotes) or a flat JSON object of
`NAME: value` pairs. `--input-format auto|dotenv|json` overrides the detection. `--dry-run` shows the names
without writing.

### `children`: discover the hierarchy

```bash
environment-store children                         # organisations
environment-store children -o acme                 # projects of acme
environment-store children -o acme -p webapp       # environments
environment-store children -o acme -p webapp -e prod   # services
environment-store children -o acme --format json   # ["webapp", ...]
```

A service has no children, so that prints nothing.

### `delete-level` (alias `rm-level`): delete a level and everything below it

Removes a level, **all of its variables and every level below it**. It cannot be undone and cannot target the root.

```bash
environment-store delete-level -o acme -p webapp --dry-run        # how many levels and variables would go
environment-store delete-level -o acme -p webapp --confirm webapp # delete it
```

You must confirm with the exact name of the deepest level you gave (`webapp` above): pass `--confirm NAME`, or on a
terminal type the name when asked. Without a terminal and without `--confirm` the command refuses. A wrong name
deletes nothing (exit code 1).

### `migrate`: apply database migrations (PostgreSQL)

```bash
environment-store --backend postgres --database-url "$URL" migrate --status   # list pending migrations
environment-store --backend postgres --database-url "$URL" migrate            # apply them (safe to re-run)
```

Needs the `postgres` extra and an existing, empty or migrated database. See
[PostgreSQL](backends.md#postgresql).

### `tui`: open the terminal UI

```bash
environment-store tui
```

Needs the `tui` extra. See the [TUI guide](tui.md).

## Transferring a store between backends

`transfer` copies every variable from the main store (the usual `--backend ...` options) into a destination store,
keeping the hierarchy. The destination uses the same options with a `--dest-` prefix, or `ENVIRONMENT_STORE_DEST_*`
variables (`--dest-backend`, `--dest-json-file`, `--dest-database-url`, `--dest-region`, `--dest-prefix`,
`--dest-parameter-type`).

```bash
# JSON file -> PostgreSQL (apply the migrations on the destination first)
environment-store --backend postgres --database-url "$URL" migrate
environment-store --backend json --json-file ./store.json transfer \
  --dest-backend postgres --dest-database-url "$URL"

# one project only, to AWS Parameter Store; preview first
environment-store --backend json --json-file ./store.json transfer -o acme -p webapp --dry-run \
  --dest-backend ssm --dest-region eu-central-1 --dest-prefix myapp
```

Behaviour:

- Variables missing in the destination are **created**; identical ones are left **unchanged**.
- Variables that exist with a **different** value are **skipped**, listed on stderr, and the command exits with
  code `3`. Add `--overwrite` to replace them.
- `-o/-p/-e/-s` copy only that level and everything below it.
- `--dry-run` reports what would happen and writes nothing. `--format json` prints the result
  (`levels`, `created`, `updated`, `unchanged`, `skipped`, `conflicts`) to stdout.
- The source is never modified. To "move" a store, delete the source yourself after checking the result.
- Source and destination must be different stores.

## Output, exit codes and scripting

- **Data goes to stdout**, status messages (`Set ...`, `Deleted ...`) and errors go to **stderr** as `error: ...`.
  It is therefore safe to capture stdout: `VALUE=$(environment-store get DB_HOST -o acme)`.
- Exit codes:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | runtime or backend error, variable not found, wrong confirmation |
| `2` | invalid arguments or hierarchy (for example `-p` without `-o`) |
| `3` | `transfer` finished but skipped conflicting variables |

- Use `--format json` where available instead of parsing text.
- Missing optional dependencies are reported with the extra to install, e.g.
  `Install the matching extra (environment-store[aws] or [postgres])`.

## Recipes

Load the variables a service needs into the current shell:

```bash
eval "$(environment-store list -o acme -p webapp -e prod -s api --resolved --format export)"
```

Write a `.env` file for local development:

```bash
environment-store list -o acme -p webapp -e dev --resolved > .env
```

Use a value in a script without printing it:

```bash
curl -H "Authorization: Bearer $(environment-store get API_KEY -o acme)" https://example.com
```

Seed a new environment from an existing `.env`:

```bash
environment-store import .env -o acme -p webapp -e staging
```

Check which environments a project has, as JSON:

```bash
environment-store children -o acme -p webapp --format json
```

Docker Compose / CI: generate the env file in a step, then use it:

```bash
environment-store list -o acme -p webapp -e prod --resolved --format dotenv > .env.prod
```
