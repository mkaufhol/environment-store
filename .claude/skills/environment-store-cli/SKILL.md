---
name: environment-store-cli
description: Use when the user asks to list, read, set, delete, import, export or run a command with environment variables or secrets kept with environment-store (the `envs` or `environment-store` command), when a project has a `.envstore.toml` file or sets ENV_STORE_CONNECTION, or when the user mentions stores, key files or passphrases for envs. Covers safe non-interactive use, key handling, merging and exit codes.
---

# environment-store CLI (`envs`)

`envs` keeps environment variables in named **stores** (name -> string value) inside a backend
(JSON or TOML files, SQLite, PostgreSQL). A store is plaintext or encrypted as a whole (AES-256-GCM,
key file or passphrase). Reading commands merge several stores in load order. `environment-store`
is the same program.

Full option tables and the error catalogue are in [reference.md](reference.md).

## Rules for agents

1. **Always pass `--noinput`** so `envs` never waits on a prompt. Without it a terminal would ask
   for keys, passphrases and confirmations. With it, a missing key fails with exit 4 and a missing
   confirmation fails with exit 1.
2. **Global options go before the command name**: `envs --noinput -c URL ls-store`. Writing
   `envs ls-store -c URL` fails with `Error: No such option: -c`.
3. **Never invent a connection.** Find it (next section). If none exists, ask the user.
4. **Do not print secret values unless the user asked for them.** Prefer `ls` (names only) over
   `ls -v`. Use `get` only for the variable you need. To hand values to a program, use `envs run`
   or `export -f FILE` (file mode 0600) instead of printing to stdout. An exported file holds
   plaintext secrets: keep it out of git (add it to `.gitignore`) and delete it when done.
5. **Secrets go in through stdin, never argv.** `envs set` refuses `KEY=VALUE` for encrypted stores
   anyway. Pipe the value from a file or another command, and never `echo` a secret literal into
   your own tool call. If the user handed you the literal value, write it to a temporary file with
   your file-writing tool (not a shell command), `chmod 600` it, redirect it into `envs set`, then
   delete it with `rm -f FILE` (plain `rm` may be aliased to `rm -i` and hang on a prompt).
6. **Confirm with the user first** before `rm`, `rm-store`, `mv-store`, `rekey`, `encrypt`,
   before `set -o` / `import -o` (overwrite), before `cp-store --plain` / `mv-store --plain`
   (writes a decrypted, unencrypted copy into the backend), and before `keygen -` (prints key
   material to stdout). Pass `-y` to `rm-store` only after the user said yes.
   `rm` has no prompt at all: it deletes immediately. `encrypt` rewrites the store in place; the
   only way back is `cp-store --plain` into a new store.
7. **Never pass a key or passphrase literally.** Keys are files (`-k path`) or stdin (`-k -`).

## Find the connection and the stores

Precedence: `-c/--connection` > `ENV_STORE_CONNECTION` > `connection` in `.envstore.toml`. There is
no default. Check in this order:

```sh
echo "${ENV_STORE_CONNECTION:-<unset>}"
# look for .envstore.toml in the current directory and its parents (up to /); prints the one in effect
d=$PWD; while :; do [ -f "$d/.envstore.toml" ] && { echo "$d/.envstore.toml"; break; }; [ "$d" = / ] && break; d=$(dirname "$d"); done
```

A project file may hold `connection`, `stores` (default load order), `ordered_overwrite` and a
`[keys]` table (store -> key file path, relative to the project file). Example:

```toml
connection = "sqlite:///envs.db"
stores = ["base", "dev", "prod"]

[keys]
prod = "keys/prod.key"
```

With that file, `envs --noinput ls` and `envs --noinput get DB_HOST` work from any subdirectory
and use the `[keys]` entry for `prod`. `--no-project` ignores the file.

Relative paths: a relative connection in `.envstore.toml` (`toml://data`, `sqlite:///envs.db`) and
its `[keys]` paths resolve against **the project file's directory**. A relative connection from
`-c` or `ENV_STORE_CONNECTION` resolves against **the current directory**.

`envs` never edits `.envstore.toml`. After `create-store -e` or `encrypt` on a store listed in
`stores`, add a `[keys]` entry yourself (or pass `-k STORE=PATH`), otherwise plain `envs ls` now
fails with exit 4.

Connection string forms:

| Backend | Example |
|---|---|
| JSON dir | `json://envs` (relative), `json:///abs/dir`, `json://~/envs` |
| TOML dir | `toml://envs`, `toml:///abs/dir` |
| SQLite | `sqlite:///envs.db` (relative), `sqlite:////abs/path/envs.db` (no `~` expansion) |
| PostgreSQL | `postgresql://user@host:5432/db?schema=environment_store` (needs the `postgres` extra) |

No setup step is needed for JSON, TOML or SQLite: the JSON/TOML directory is created on the first
write and the SQLite file (and its schema) on first use. `envs migrate` is only for PostgreSQL.
A JSON/TOML directory that does not exist yet just looks empty: `ls-store` prints nothing and exits
0. If `ls-store` is empty, check the connection for a typo before assuming there are no stores.

## Keys, non-interactively

| Command kind | Key option |
|---|---|
| Reading: `ls`, `get`, `export`, `export-shell`, `run` | `-k STORE=PATH` (repeatable); `-k PATH` only when exactly one store is read; `-k STORE=-` reads stdin |
| Writing: `set`, `rm`, `import`, `rekey` (old key), `cp-store`/`mv-store` (source key) | `-k PATH` or `-k -` |
| Not needed: `ls-store`, `rm-store`, `keygen` | none |

An encrypted store needs its key even for a names-only `ls`: names and values are encrypted
together. Only `ls-store`, `rm-store` and `keygen` work without it.

The store's mode decides how the file is read: a key file (`envstore-key-v1:...`) for keyfile
stores, a UTF-8 passphrase file (one trailing newline stripped) for passphrase stores. Order of key
sources: `-k` > `[keys]` in the project file > prompt (never with `--noinput`) > exit 4.
`ls-store` shows each store's mode: `plain`, `encrypted (keyfile)`, `encrypted (passphrase)`.

Stdin can be used for **one** thing per command: either the value of `set KEY` or `-k -`, not both.
Key from a password manager: `op read 'op://vault/prod/key' | envs --noinput get DB_HOST base prod -k prod=-`.

## Command cheat sheet (all verified)

```sh
envs --noinput ls-store [--json]                      # stores + encryption; needs no key
envs --noinput ls [STORES...] [-v] [--source] [--first-wins] [--json] [-k STORE=PATH]...
envs --noinput get KEY [STORES...] [--first-wins] [--json] [-k STORE=PATH]...
envs --noinput set -s STORE [-o] KEY=VALUE...         # plaintext stores only; store must exist
envs --noinput set -s STORE [-o] [-k PATH] KEY < value-file   # one KEY, value from stdin
envs --noinput rm -s STORE [-k PATH] KEY...           # no confirmation prompt
envs --noinput import -s STORE [-f FILE|-] [-t dotenv|json|toml] [-o] [-k PATH]
envs --noinput export [STORES...] [-f FILE] [-t dotenv|json|toml] [--force] [--first-wins] [--nested] [-k STORE=PATH]...
envs --noinput export-shell [STORES...] [-o] [--first-wins] [--nested] [-k STORE=PATH]...   # prints values!
envs --noinput run [STORES...] [-o] [--first-wins] [--nested] [-k STORE=PATH]... -- CMD [ARGS...]
envs --noinput create-store NAME [-e (-k PATH | --generate-key PATH | --passphrase)]
envs --noinput rm-store NAME -y                       # only after the user confirmed
envs --noinput cp-store SRC DST [--to URL] [-k PATH] [--plain | --new-key PATH | --generate-key PATH | --passphrase]
envs --noinput mv-store SRC DST [same options as cp-store]
envs --noinput encrypt -s STORE (--new-key PATH | --generate-key PATH | --passphrase)
envs --noinput rekey -s STORE -k OLD (--new-key PATH | --generate-key PATH | --passphrase)
envs keygen PATH            # new key file, mode 0600, never overwrites; needs no connection
envs --noinput migrate      # PostgreSQL only in practice: SQLite/JSON/TOML set themselves up
```

Notes that trip agents up:

- `get` takes the **variable first**, then the stores: `envs --noinput get DB_HOST base dev`.
  It prints the raw value with **no trailing newline** when stdout is not a terminal.
- `set`, `rm`, `import`, `encrypt`, `rekey` **always need `-s STORE`**; they never take the store
  from the project file.
- **`set` and `import` never create a store.** A missing store fails with exit 2,
  `store 'base' not found in ...`. Run `create-store NAME` first (only if the user asked for it).
- Options may follow the positional stores: `run base dev --first-wins -- CMD` is fine. Everything
  after the first `--` belongs to the command.
- `run` and `export-shell` **keep variables already set in the caller's environment** unless `-o`
  is given. When checking a merge result, a stray `A` in your own environment wins over the stores.
- **`set -s STORE KEY` with an empty stdin (e.g. `< /dev/null`) stores an empty string and succeeds.** Always
  pipe or redirect the value explicitly. Exactly one trailing newline is stripped; to keep a
  trailing newline use `import`.
- Positional stores on reading commands **replace** the project file's `stores`.
- `--passphrase` reads the passphrase from stdin when piped: `envs --noinput create-store customer-a -e --passphrase < customer-a.pass`.
- `--new-key PATH` uses an **existing** key file (e.g. from `envs keygen PATH`; a missing file is
  exit 4). `--generate-key PATH` **creates** a new key file (mode 0600), refuses to overwrite an
  existing file (exit 1), refuses `-`, and needs an existing parent directory (`mkdir -p keys`).
- Key files are secrets: keep them out of git (e.g. `keys/` or `*.key` in `.gitignore`).
- `cp-store --plain` is the only way to decrypt (there is no `decrypt` command).
- Store names: `^[a-z][a-z0-9_-]{0,62}$` (`dev`, `customer-a`; not `Prod`, not `1st`). Variable
  names: `^[A-Za-z_][A-Za-z0-9_]*$`.

## Recipes

```sh
# Set up a new project (only when the user asked for it)
cat > .envstore.toml <<'EOF'
connection = "toml://data"
stores = ["base", "dev"]
EOF
envs --noinput create-store base
envs --noinput create-store dev
envs --noinput set -s base APP_NAME=demo
envs --noinput ls
# APP_NAME

# Encrypt an existing store with a new key file, then register the key
mkdir -p keys
envs --noinput encrypt -s dev --generate-key keys/dev.key
# encrypted store 'dev' (keyfile)
printf '\n[keys]\ndev = "keys/dev.key"\n' >> .envstore.toml   # envs does not do this for you
# and add keys/ to .gitignore

# What is there? (no values printed)
envs --noinput -c sqlite:///envs.db ls-store
envs --noinput -c sqlite:///envs.db ls base dev prod -k prod=keys/prod.key --source
# DB_HOST      dev
# DB_PASSWORD  prod
# DB_PORT      base
# ...

# Add a secret to an encrypted store without it touching argv or shell history
envs --noinput set -s prod -k keys/prod.key DB_PASSWORD < /path/to/secret.txt
# set DB_PASSWORD in store 'prod'

# Run tests with merged variables (values never printed)
envs --noinput run base dev prod -k prod=keys/prod.key -- pytest -q

# Write a .env for a tool that needs a file (mode 0600; refuses to overwrite without --force)
# The file holds plaintext secrets: keep it in .gitignore and delete it afterwards
envs --noinput export base dev -f .env
# exported to '.env'
envs --noinput export base prod -k prod=keys/prod.key -f .env   # with an encrypted store

# Load into a POSIX shell (bash/zsh/dash; fish/PowerShell: use run)
eval "$(envs --noinput export-shell base dev)" && ./manage.py check
```

`export-shell` on its own **prints every value to stdout**; only run it inside `eval "$(...)"`
unless the user wants to see the values. Values are single-quoted for POSIX `sh`. Without `-o`
each line keeps an existing variable; with `-o` the lines are plain `export`:

```text
$ envs --noinput export-shell base            $ envs --noinput export-shell base -o
[ -n "${A+x}" ] || export A=1                 export A=1
[ -n "${SP+x}" ] || export SP='a b'           export SP='a b'
```

Each agent tool call usually starts a fresh shell, so variables loaded with `eval` are gone by the
next call. Prefer `envs run ... -- CMD`, or chain `eval` and the command in the same call as above.

## Machine-readable output

Data goes to stdout as UTF-8; messages (`created store 'x'`, `Error: ...`) go to stderr.
Output is sorted by variable name (`ls-store` by store name).

- `ls-store --json`: list of `{created_at, encrypted, key_mode, name, revision, updated_at}`;
  `key_mode` is `"keyfile"`, `"passphrase"` or `null`.
- `ls --json`: list of `{"name": ...}`, plus `"value"` with `-v` and `"store"` with `--source`.
- `get --json`: one object with keys `name`, `store` (the winner), `value`, printed **indented over
  several lines** with a trailing newline (parse it, do not match the text). Raw `get` (no
  `--json`) has no trailing newline.
- `export -t json`: one flat object; with `--nested` one object per store.

## Merging and `--nested`

Stores are applied left to right; by default **the last store wins**. `--first-wins` (or
`ENV_STORE_ORDERED_OVERWRITE=false`, or `ordered_overwrite = false` in the project file) makes the
first store win. `--source` shows which store each winning value came from:

```text
$ envs --noinput ls -v --source base dev           $ envs --noinput ls -v --source --first-wins base dev
DB_HOST=dev.example.com  dev                        DB_HOST=localhost  base
DB_PORT=5432             base                       DB_PORT=5432       base
```

`--nested` (on `export`, `export-shell`, `run`) does not merge: each variable becomes
`STORE__NAME`, with the store upper-cased and `-` turned into `_` (`customer-a` + `DB_HOST` ->
`CUSTOMER_A__DB_HOST`). JSON/TOML nested export gives one table per store. A store listed twice, or
two stores producing the same flat name (`customer-a` and `customer_a`), is an error.

`run` and `export-shell` keep variables already set in the environment unless `-o` is given.

## Exit codes and what to do

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | |
| 1 | usage, validation, configuration or backend error; missing confirmation under `--noinput` | Read the `Error:` line. No connection: find or ask for one. Missing confirmation: ask the user, then add `-y`. |
| 2 | store or variable not found (a missing store is reported first) | Read the `Error:` line to tell which. Check names with `ls-store` / `ls`. Do not create the store unless the user asked. |
| 3 | already exists | Ask before adding `-o` (variables) or choosing another store name. |
| 4 | key problem: missing, wrong, unreadable, or wrong kind (key file vs passphrase) | Ask the user for the key file path; check the `[keys]` entry. Never guess or generate a new key for an existing store. |
| 5 | concurrent modification; nothing was written | Run the same command again. |
| 126 / 127 | `run` only: command not executable / not found | Fix the command after `--`. |
| other | `run` passes the command's own exit code through | Treat as the command's result. |

## Common errors

| Message (stderr) | Fix |
|---|---|
| `no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, ...` | Find the connection (above) or ask; never invent one. |
| `No such option: -c` | Move `-c`/`--noinput` before the command name. |
| `no stores given: name stores, or set 'stores' in .envstore.toml` (1) | Name the stores positionally (`ls base dev`), or check `stores` in `.envstore.toml`. |
| `store 'prod' is encrypted and no key or passphrase was given: pass it with -k prod=<path> ...` (4) | Add `-k prod=PATH` (or `-k PATH` with one store). |
| `-k <path> without a store name works with exactly one store ...` (1) | Use `-k STORE=PATH` per encrypted store. |
| `cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified` (4) | Wrong key file; ask the user. |
| `store 'customer-a' uses a passphrase, but a key file was given` (4) | Point `-k` at the passphrase file. |
| `store 'base' is not encrypted; it takes no key or passphrase` (1) | Drop the `-k` for that store. |
| `variables already exist in store 'dev': DEBUG; use overwrite (-o/--overwrite) ...` (3) | Confirm, then add `-o`. Nothing was written. |
| `variable 'NOPE' not found in stores 'base', 'dev'` (2) | Check spelling and the store list. |
| `store 'base' not found in /path/to/stores` (2) | Check `ls-store` and the connection; `set`/`import` need `create-store` first. |
| `key file 'prod.key' already exists; refusing to overwrite it` (1) | Pick another path, or use `--new-key PATH` / `-k PATH` to use the existing file. |
| `cannot read key file 'x.key': No such file or directory` (4) | Wrong path; `--new-key` and `-k` need an existing file. |
| `store 'dev' is already encrypted: use 'envs rekey -s dev'` (1) | Use `rekey` to change the key. |
| `store 'prod' is encrypted: values on the command line end up in the shell history ...` (1) | Use `set -s prod -k KEY NAME < file`. |
| `Delete store 'dev'? Confirm with -y/--yes (no terminal to ask, or --noinput)` (1) | Ask the user; rerun with `-y` only after a yes. |
| `output file '.env' already exists; use force (--force) to replace it` (1) | Ask, then add `--force`, or pick another path. |
| `stdin can be used only once per command ...` (1) | Put the key in a file and use `-k PATH`. |
| `this feature needs the optional 'cli' dependencies: pip install 'environment-store[cli]'` | Install the named extra (`cli`, `postgres`, `tui`). |

`envs tui` is interactive and refused under `--noinput`; agents should not use it.
