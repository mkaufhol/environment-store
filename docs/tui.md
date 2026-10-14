# Terminal UI

An interactive terminal UI to browse and edit a store, built with [Textual](https://textual.textualize.io/).
It does the same as the [CLI](cli.md) and [Python API](python-usage.md), just interactively.

## Install and start

The TUI needs the `tui` extra (or `full`), see [Installation](installation.md):

```bash
uv add "environment-store[tui]"
```

Start it with the same backend options as the CLI. They go **before** `tui`:

```bash
environment-store --backend json --json-file ./store.json tui

# or via environment variables
export ENVIRONMENT_STORE_BACKEND=postgres
export ENVIRONMENT_STORE_DATABASE_URL=postgresql+psycopg://user:pass@localhost/environment_store
environment-store tui
```

Run it once without installing anything:

```bash
uvx --from "environment-store[tui]" environment-store --backend json --json-file ./store.json tui
```

The backend options are listed in the [CLI guide](cli.md#choosing-a-backend).

## The screen

```
┌────────────────────┐┌─────────────────────────────────────────────────────┐
│ ▼ root             ││ acme / webapp / prod  (own variables)               │
│   ▼ acme           ││ Name         Value                                  │
│     ▼ webapp       ││ LOG_LEVEL    ***                                    │
│       ▶ prod       ││ DB_HOST      ***                                    │
└────────────────────┘└─────────────────────────────────────────────────────┘
```

- **Left: the tree** of levels: organisation > project > environment > service. Children load when you expand a
  node. The first node, `root`, is the root level.
- **Right: the variables** of the selected level. The line above the table shows the level and whether you see its own variables or
  the [resolved](#resolved-view) ones.
- **Values are hidden** (`***`) until you press `v`, so a screen share does not leak secrets.

Selecting a node in the tree immediately shows that level's variables.

## Keys

| Key | Action |
|---|---|
| `↑` `↓` or `k` `j` | move up / down |
| `→` or `l` | tree: expand the node, then step into its first child; on a node without children switch to the variables table |
| `←` or `h` | tree: collapse the node, or go to its parent if it is already collapsed; table: back to the tree |
| `a` | add a variable at the selected level |
| `e` | edit the highlighted variable |
| `d` | delete the highlighted variable (asks for confirmation) |
| `n` | create a new child level under the selected node |
| `x` | delete the selected level and everything below it (type its name to confirm) |
| `r` | toggle the resolved view |
| `v` | show / hide values |
| `F5` | reload the tree and the table from the store |
| `Esc` | cancel a dialog |
| `q` | quit |

The footer always shows the available keys.

## Working with variables

**Add (`a`)**: asks for a name and a value and saves them at the selected level.

**Edit (`e`)**: edits the value of the highlighted variable. The name is fixed.

**Delete (`d`)**: asks for confirmation, then removes that variable only.

## Resolved view

Press `r` to see what a level actually receives: its own variables merged with all parent levels, deeper values
winning. For `acme / webapp / prod / api` that is root, organisation, project, environment and service variables
combined.

The resolved view is read-only. Press `r` again to go back to the level's own variables before editing or
deleting.

## Creating levels

A level exists as long as it holds a variable, so creating one means creating its first variable.

Select the parent node and press `n`. The dialog is titled with the kind of level you are creating (an organisation
under `root`, a project under an organisation, ...). Enter the new level's name, a first variable name and its value.
The tree reloads and moves to the new level. On a service, `n` shows a warning, because services have no children.

## Deleting a level

Select the level and press `x`. A warning states how many levels and variables below it will be removed, and that this
cannot be undone. **The Delete button stays disabled until you type the level's exact name.** `Esc` or `Cancel`
aborts. Afterwards the cursor moves to the parent.

The root level cannot be deleted.

## What the TUI does not do

Bulk administration is CLI only: [`import`](cli.md#import-set-many-variables-from-a-file),
[`transfer`](cli.md#transferring-a-store-between-backends) and [`migrate`](cli.md#migrate-apply-database-migrations-postgresql).
The TUI shows an error notification if the backend fails (for example, missing database tables), instead of crashing.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `The TUI needs the tui extra` | install `environment-store[tui]` |
| `No backend selected` | pass `--backend` before `tui`, or set `ENVIRONMENT_STORE_BACKEND` |
| error notification about a missing table on a new PostgreSQL database | run `environment-store migrate` first |
| tree looks stale after changes from another process | press `F5` |
| garbled colours or characters | use a terminal with true-colour and UTF-8 support |
