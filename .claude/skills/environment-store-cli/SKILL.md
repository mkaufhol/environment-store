---
name: environment-store-cli
description: Read and manage hierarchical environment variables (organisation > project > environment > service) with the `environment-store` CLI. Use when asked to get, set, list, delete, import or export environment variables/secrets, to load an environment's config for a service, or to inspect which orgs/projects/environments/services exist in the store.
---

# environment-store CLI

Manages variables in a hierarchy: **organisation > project > environment > service > variable**.
Names are unique per level, not across levels. Levels cannot be skipped
(`-p` needs `-o`, `-e` needs `-p`, `-s` needs `-e`). No hierarchy flags = root level.

Run it as `environment-store ...` (or `uv run environment-store ...` / `python -m environment_store ...`).

## 1. Backend (check this first)

A backend must be selected, via flags or env vars. Check the environment before asking the user:

```bash
env | grep '^ENVIRONMENT_STORE_'
```

| Backend | Selected with | Needs |
|---|---|---|
| `json` | `--backend json` | `--json-file PATH` / `ENVIRONMENT_STORE_JSON_FILE` |
| `postgres` | `--backend postgres` | `--database-url URL` / `ENVIRONMENT_STORE_DATABASE_URL` |
| `ssm` | `--backend ssm` | `--region` / `ENVIRONMENT_STORE_REGION` / `AWS_REGION`; optional `--prefix`, `--parameter-type` |
| `secretsmanager` | `--backend secretsmanager` | region as above; optional `--prefix` |

`ENVIRONMENT_STORE_BACKEND` sets the backend. Backend flags go **before** the subcommand:
`environment-store --backend json --json-file s.json list -o acme`.
AWS credentials come from the normal boto3 chain. If the user has not told you which backend/store
to use and none is configured, ask — never guess a production store. Prefer a throwaway `json` file for experiments.

## 2. Commands

Hierarchy flags (all commands except where noted): `-o ORG -p PROJECT -e ENV -s SERVICE`.

```bash
environment-store get NAME -o acme -p web -e prod            # prints raw value; exit 1 if missing
environment-store get NAME --format json                      # {"name":..,"value":..}
environment-store set NAME VALUE -o acme -p web               # create or update
printf %s "$SECRET" | environment-store set NAME --stdin      # keep secrets out of argv/history
environment-store set NAME --from-file ./cert.pem
environment-store list -o acme -p web -e prod                 # only that level, NAME=value lines
environment-store list ... --resolved                         # merged with parent levels, deeper wins
environment-store list ... --format json|dotenv|export|table
environment-store list ... --names-only                       # no values
environment-store list ... --mask                             # values shown as ***
environment-store delete NAME [NAME...] -o acme --yes
environment-store import .env -o acme -p web -e dev           # .env or flat JSON, `-` = stdin
environment-store import vars.json ... --dry-run              # preview, writes nothing
environment-store delete-level -o acme -p web --dry-run      # preview: sub-levels and variables affected
environment-store delete-level -o acme -p web --confirm web  # delete the level and EVERYTHING below it
environment-store transfer --dest-backend postgres --dest-database-url URL --dry-run   # copy store -> other backend
environment-store children                                    # list organisations
environment-store children -o acme [-p web [-e dev]]          # projects / environments / services
```

Postgres only: `environment-store migrate --status` lists pending schema migrations and
`environment-store migrate` applies them. Run it once on a fresh database (the database must already exist);
"relation environment_store does not exist" errors mean migrations haven't been applied.

## 3. Efficient workflows

- **Discover first:** `children` (then `children -o X`, `-o X -p Y`, ...) to learn exact names before reading or writing. Names are case-sensitive.
- **Effective config for a service:** use `list ... --resolved --format json` at the deepest level rather than querying each level yourself. Plain `list` returns only that one level.
- **Parse programmatically:** use `--format json` (a `{NAME: value}` object) and `children --format json` (array). Don't scrape table output.
- **Export into a shell:** `eval "$(environment-store export -o a -p b -e prod)"` — only when the user wants the variables in the current shell.
- **Bulk changes:** one `import` call beats many `set` calls. Run with `--dry-run` first.
- **Single value in a script:** `VAL=$(environment-store get NAME -o a)`; use `--raw` to drop the trailing newline.

## 4. Safety rules

- Values are often secrets. Use `--names-only` or `--mask` when you only need to know *what exists*; don't print or paste values into chat, commits or logs unless the user asks.
- Pass secret values via `--stdin` / `--from-file`, not as command-line arguments.
- `set` silently overwrites an existing value, and `delete` is permanent (SecretsManager deletes without a recovery window). Before modifying prod-like levels, `get` the current value and confirm intent with the user.
- `delete` prompts only on an interactive TTY; agents must pass `--yes`, so confirm with the user first.
- Setting at a higher level (root/org) changes the resolved result for everything below it unless overridden.

## 5. Deleting a level

`delete-level` removes a whole organisation/project/environment/service with all variables and all levels below
it. It is irreversible and cannot target the root. It always needs `--confirm NAME` with the exact name of the
deepest level given (agents run without a terminal, so there is no prompt). Always run `--dry-run` first, show the
user the numbers and get an explicit yes before passing `--confirm`. Never fill `--confirm` from the user's
general request such as "clean up".

## 6. Transferring between backends

`transfer` copies the store selected by the main options (`--backend ...`) into the destination given with
`--dest-backend`, `--dest-json-file`, `--dest-database-url`, `--dest-region`, `--dest-prefix`
(or `ENVIRONMENT_STORE_DEST_*`). Add `-o/-p/-e/-s` to copy only a subtree. The source is never changed.

- Always run `--dry-run` first and report the counts to the user.
- Existing destination variables with a different value are skipped (listed on stderr, exit code `3`).
  Only pass `--overwrite` after the user has seen the conflicts and agreed.
- For a postgres destination run `environment-store --backend postgres --database-url URL migrate` first.
- Use `--format json` to read the result programmatically (`created`, `updated`, `unchanged`, `skipped`, `conflicts`).

## 7. Output & errors

- Data goes to stdout; status messages (`Set ...`, `Deleted ...`) and errors go to stderr as `error: ...`.
- Exit codes: `0` ok, `1` runtime/backend error or variable not found, `2` invalid hierarchy/arguments, `3` `transfer` skipped conflicting variables.
- Common fixes: "No backend selected" → set `--backend`/env; "requires organisation" → add the missing parent flag; "missing dependency" → install the extra (`environment-store[aws]` or `[postgres]`).
- Backend naming limits: AWS backends allow only `a-zA-Z0-9_.-` in names and prefix.

## 8. Don't use `tui`

`environment-store tui` opens an interactive full-screen UI for humans. Agents must not run it; use the commands above.
