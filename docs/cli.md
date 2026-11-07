<p align="center">
  <img src="assets/environment-store-logo.svg" alt="Environment Store logo" width="120">
</p>

# Environment Store CLI guide

`envs` keeps environment variables in named **stores**. You can encrypt any store, combine several stores, and load the result into a shell, a process, a `.env` file or a Python program.

This guide covers the command line from start to finish. It starts with the ideas you need, then describes every command, and ends with recipes for common jobs. New here? The [quick start page](quickstart.md) is a shorter walk-through. For the Python API, see [python.md](python.md); all pages are listed in the [docs index](README.md).

All examples on this page were run against `environment-store 2.0.0.dev0`. The output shown is real. Lines such as `created store 'base'` are status messages printed on **stderr**; data (values, listings, exports) goes to **stdout**.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Concepts](#concepts)
  - [Connection: where stores live](#connection-where-stores-live)
  - [Stores and variables](#stores-and-variables)
  - [Combining several stores](#combining-several-stores)
  - [Keys and encryption](#keys-and-encryption)
    - [Keeping secrets safe](#keeping-secrets-safe)
  - [The project file `.envstore.toml`](#the-project-file-envstoretoml)
- [Global options and environment variables](#global-options-and-environment-variables)
- [Commands](#commands)
  - [Stores: `ls-store`, `create-store`, `rm-store`, `cp-store`, `mv-store`](#stores)
  - [Variables: `ls`, `get`, `set`, `rm`, `import`](#variables)
  - [Export and run: `export`, `export-shell`, `run`](#export-and-run)
  - [Keys and encryption: `keygen`, `encrypt`, `rekey`](#keys-and-encryption-commands)
  - [Terminal UI: `tui`](#terminal-ui-tui)
  - [Database schema: `migrate`](#database-schema-migrate)
- [Output modes](#output-modes)
- [Exit codes](#exit-codes)
- [Recipes](#recipes)
- [Reference pages: man and tldr](#reference-pages-man-and-tldr)
- [Troubleshooting](#troubleshooting)

---

## Install

Environment Store needs Python 3.13 or newer. The CLI is the optional `cli` extra. These docs use [uv](https://docs.astral.sh/uv/): `uv tool install` puts `envs` into its own isolated environment and links the command onto your `PATH`, so it never mixes with other packages and needs no global `pip`. `uvx` runs it once without installing anything.

```sh
uv tool install 'environment-store[cli]'            # CLI with JSON, TOML and SQLite backends
uv tool install 'environment-store[cli,postgres]'   # ... plus PostgreSQL
uv tool install 'environment-store[all]'            # CLI, PostgreSQL and the terminal UI
uvx --from 'environment-store[cli]' envs --version  # run once, without installing
```

**2.0 is not on PyPI yet**, so today these commands would find the old 0.1 line. Until the release, install from the repository with the same extras:

```sh
uv tool install 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2'
```

With pip, use `pip install 'environment-store[cli]'` inside a virtual environment. [installation.md](installation.md) has the details: every extra in a table, the library install with `uv add`, installing from a clone, and pip.

| Extra | Adds |
|---|---|
| `cli` | the `envs` command (also installed as `environment-store`) |
| `postgres` | the PostgreSQL backend |
| `tui` | `envs tui` (needs `cli` as well) |
| `all` | all of the above |

Check the install:

```console
$ envs --version
environment-store 2.0.0.dev0
```

`envs` and `environment-store` are the same program, and `python -m environment_store.cli` works too. If an extra is missing, the command tells you which one to install, for example `Error: this feature needs the optional 'postgres' dependencies: uv add 'environment-store[postgres]' (or pip install 'environment-store[postgres]'); for the CLI tool: uv tool install 'environment-store[cli,postgres]'`. For the `envs` tool, use the last command: it reinstalls the tool with the extra added (list any other extras the tool already has, too).

`envs -h` is short for `envs --help`, on `envs` itself and on every command (`envs export -h`). The same reference is also available as a man page and a tldr page; see [Reference pages](#reference-pages-man-and-tldr).

---

## Quick start

Create two stores in a local folder, fill them, and use them:

```console
$ export ENV_STORE_CONNECTION=json://envs
$ envs create-store base
created store 'base'
$ envs create-store dev
created store 'dev'
$ envs set -s base DB_HOST=localhost DB_PORT=5432 LOG_LEVEL=info
set DB_HOST, DB_PORT, LOG_LEVEL in store 'base'
$ envs set -s dev DB_HOST=dev.example.com DEBUG=false
set DB_HOST, DEBUG in store 'dev'
$ envs ls -v base dev
DB_HOST=dev.example.com
DB_PORT=5432
LOG_LEVEL=info
DEBUG=false
$ envs run base dev -- python3 -c 'import os; print(os.environ["DB_HOST"])'
dev.example.com
```

`dev` was listed last, so its `DB_HOST` wins over the one in `base`. The next section explains this and the other basics.

These two stores are **plain**: the files in `envs/` hold the values as readable text. Before you put a password in a store, read [Keeping secrets safe](#keeping-secrets-safe).

---

## Concepts

### Connection: where stores live

Every command that touches stores needs a **connection string**. It names the backend and the location:

| Backend | Connection string | Notes |
|---|---|---|
| JSON files | `json://envs` (relative to the current directory), `json:///abs/dir`, `json://~/envs` | One `<store>.json` file per store, plus a hidden lock file. Files are created with mode 0600. A missing folder is created on first write, with mode 0700. |
| TOML files | `toml://envs`, `toml:///abs/dir`, `toml://~/envs` | Same layout with `.toml` files. |
| SQLite | `sqlite:///envs.db` (relative, three slashes), `sqlite:////home/me/envs.db` (absolute, four slashes), `sqlite:///~/envs.db` (home directory) | One database file, mode 0600. A missing parent folder is created on first write, with mode 0700. The schema is created and upgraded automatically. |
| PostgreSQL | `postgresql://user@host:5432/db` or `postgres://...`, optional `?schema=name` | Needs the `postgres` extra. The schema defaults to `environment_store`. |

You give the connection in one of three ways. The first one found wins:

1. `-c URL` / `--connection URL` on the command line, before the command name: `envs -c json://envs ls-store`.
2. The environment variable `ENV_STORE_CONNECTION`.
3. `connection = "..."` in the [project file](#the-project-file-envstoretoml).

There is no default. Without a connection you get:

```console
$ envs ls-store
Error: no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set 'connection' in .envstore.toml
```

A few more connection errors you may meet:

```console
$ envs -c redis://x ls-store
Error: unsupported connection scheme 'redis': use one of json, postgres, postgresql, sqlite, toml
$ envs -c envs ls-store
Error: a connection string must start with 'scheme://', e.g. json://path/to/dir, sqlite:///envs.db or postgresql://host/db
$ envs -c 'json://envs?x=1' ls-store
Error: a json:// connection string takes no query or fragment ('?', '#'); name only the directory, e.g. json://envs
```

A typo in a path is not an error: the backend is simply empty. `ls-store` then names the location it looked at on stderr, so you can spot the typo. Reading creates no file or folder:

```console
$ envs -c json://emvs ls-store
no stores in /home/me/project/emvs
```

**PostgreSQL notes.** These come from the code and spec; they were not run for this guide.

- In the user name and password, percent-encode `@`, `/` and `?` (`%40`, `%2F`, `%3F`).
- `?schema=` must match `[a-z_][a-z0-9_]{0,62}`. Every other query parameter is passed to libpq unchanged, for example `?sslmode=require`.
- Keep passwords in `ENV_STORE_CONNECTION`, not in the project file. A password in the project file triggers a warning on every command that reads the file. The tool never prints passwords.
- The schema is created on first use. If your database user lacks the `CREATE` privilege, an administrator runs `envs migrate` once. After an upgrade of Environment Store, PostgreSQL refuses an older schema until someone runs `envs migrate` (SQLite upgrades itself). See [migrate](#database-schema-migrate).

### Stores and variables

A **store** is a named set of variables. Store names:

- are 1 to 63 characters long,
- use lowercase letters, digits, `_` and `-`,
- start with a letter (pattern `^[a-z][a-z0-9_-]{0,62}$`).

Good names: `base`, `dev`, `prod`, `customer-a`, `team_x`. The rule keeps names usable as shell variable prefixes (see [nested mode](#nested-mode)).

```console
$ envs -c json://envs create-store Dev
Error: invalid store name 'Dev': use 1 to 63 lowercase letters, digits, '_' or '-', starting with a letter (^[a-z][a-z0-9_-]{0,62}$)
```

A **variable** has a POSIX name (letters, digits and `_`, not starting with a digit; case-sensitive) and a string value. A value can be any UTF-8 text, including empty and multi-line text.

```console
$ envs -c json://envs set -s dev 9BAD=x
Error: invalid variable name '9BAD': use letters, digits and '_', not starting with a digit (^[A-Za-z_][A-Za-z0-9_]*$)
```

The variables of one store are listed sorted by name, and `ls-store` sorts the stores by name. When you combine several stores, the output follows the load order instead; see [Output order](#output-order).

### Combining several stores

Reading commands (`ls`, `get`, `export`, `export-shell`, `run`) take a list of stores in **load order**. When a variable appears in more than one store, **the last store wins** by default. This lets you layer a general store with a more specific one:

```console
$ envs ls -v --source base dev
DB_HOST=dev.example.com  dev
DB_PORT=5432             base
LOG_LEVEL=info           base
DEBUG=false              dev
```

To make the **first** store win instead, use `--first-wins`:

```console
$ envs ls -v --source --first-wins base dev
DB_HOST=localhost  base
DB_PORT=5432       base
LOG_LEVEL=info     base
DEBUG=false        dev
```

#### Output order

Merged output lists the variables **store by store, in load order**. Within one store they are sorted by name. A variable that appears in several stores stays at the position where it first appears and gets the value the merge order picks. Above, `base` contributes `DB_HOST`, `DB_PORT` and `LOG_LEVEL` (sorted), then `dev` adds `DEBUG`; `DB_HOST` stays first but takes `dev`'s value.

Another example, with two stores:

```console
$ envs create-store store-a
created store 'store-a'
$ envs set -s store-a ENV=development DEBUG=True
set ENV, DEBUG in store 'store-a'
$ envs create-store store-b
created store 'store-b'
$ envs set -s store-b ENV=staging DB_NAME=test
set ENV, DB_NAME in store 'store-b'
$ envs export store-a store-b
DEBUG=True
ENV=staging
DB_NAME=test
$ envs export --first-wins store-a store-b
DEBUG=True
ENV=development
DB_NAME=test
```

`store-a` comes first, so its names come first, sorted: `DEBUG`, `ENV`. `store-b` only adds `DB_NAME` at the end; its `ENV` replaces the value but not the position. The order is the same for `ls` (also with `--json`), every `export` format, `export-shell` and `run`. A store's own variables are sorted by name, not kept in the order you set them.

#### Changing which store wins

Besides `--first-wins`, you can flip the default with `ENV_STORE_ORDERED_OVERWRITE=false` or `ordered_overwrite = false` in the project file. The rule, strongest first:

1. `--first-wins` on the command line.
2. `ENV_STORE_ORDERED_OVERWRITE` (`true`/`false`/`1`/`0`/`yes`/`no`, any case; `true` means last wins).
3. `ordered_overwrite` in the project file.
4. Default: last wins.

There is no `--last-wins` flag. If an environment variable or project file sets first-wins and you need last-wins for one command, reorder the stores instead.

#### Nested mode

Sometimes you want every store's variables kept apart rather than merged. `export`, `export-shell` and `run` accept `--nested`:

- For JSON and TOML output, each store becomes its own object or table.
- For dotenv, shell and `run`, each variable is prefixed with its store name: `STORE__NAME`. The store name is upper-cased and `-` becomes `_`, so `customer-a` + `DB_HOST` becomes `CUSTOMER_A__DB_HOST`.

```console
$ envs run --nested base dev -- sh -c 'echo "$BASE__DB_HOST $DEV__DB_HOST"'
localhost dev.example.com
```

Two stores can map to the same prefix (`customer-a` and `customer_a` both become `CUSTOMER_A`). Their variables then share one prefix, and you can no longer tell which store each came from. If both stores contain the same variable, nested dotenv/shell/run output fails. Nested mode also needs each store only once:

```console
$ envs export --nested customer-a customer_a
CUSTOMER_A__X=1
CUSTOMER_A__Y=2
$ envs set -s customer_a X=3
set X in store 'customer_a'
$ envs export --nested customer-a customer_a
Error: nested key CUSTOMER_A__X is produced by both X in store 'customer-a' and X in store 'customer_a'; rename one of them or export without nested mode
$ envs export --nested customer-a customer-a
Error: store 'customer-a' is listed more than once; nested mode needs each store once
```

### Keys and encryption

A store is either plain or **encrypted as a whole**. A plain store is saved as readable text: anyone who can read the JSON or TOML file or the database can read every value. In an encrypted store, the names and the values are both encrypted (AES-256-GCM). Even `ls-store` shows only the store's name and that it is encrypted.

[encryption.md](encryption.md) explains the cryptography and key handling in more depth. There are two kinds of secret:

| Key mode | What you keep | How to create it |
|---|---|---|
| `keyfile` | a key file with a random 256-bit key | `envs keygen PATH`, or `--generate-key PATH` on the command that encrypts |
| `passphrase` | a passphrase you choose (stretched with Argon2id) | `--passphrase` on the command that encrypts |

A **key file** is one line of text. You can keep it in a file or in a password manager:

```text
envstore-key-v1:<43 characters>
```

A **passphrase file** is a text file containing the passphrase. One trailing newline is ignored.

#### Giving a key to a command

Every option that takes a key, `-k`, accepts a path to a key file or a passphrase file. The store's own mode decides how the file is read. `-k -` reads the key from stdin. `~` is expanded.

When a command needs a key, it looks in this order:

1. `-k` on the command line.
2. The environment variable `ENV_STORE_KEY_<STORE>`: the store name in upper case with `-` turned into `_` (`ENV_STORE_KEY_CUSTOMER_A` for `customer-a`), holding the key line or the passphrase itself. Only for existing stores; for deployments where no key file can be shipped (see [Deploying with encrypted stores](deployment.md)).
3. The `[keys]` table of the project file.
4. A hidden prompt, `Key or passphrase for store 'prod': `, when you are at a terminal. At the prompt you type the key line or the passphrase itself.
5. Otherwise the command stops with exit code 4:

```console
$ envs ls -v prod
Error: store 'prod' is encrypted and no key or passphrase was given; pass it with -k <path> (or -k - for stdin), or set ENV_STORE_KEY_PROD
```

**Reading commands with several stores.** `ls`, `get`, `export`, `export-shell` and `run` bind each key to its store with `-k STORE=PATH`. Repeat `-k` for several encrypted stores. With exactly one store, plain `-k PATH` is enough:

```console
$ envs ls -v prod -k prod.key
DB_HOST=db.prod.internal
DB_PASSWORD=hunter2
$ envs ls -v base prod -k prod.key
Error: -k <path> without a store name works with exactly one store; with several stores bind each key by name: -k <store>=<path>
$ envs ls -v --source base prod -k prod=prod.key
DB_HOST=db.prod.internal  prod
DB_PORT=5432              base
LOG_LEVEL=info            base
DB_PASSWORD=hunter2       prod
```

Only the text before the first `=` that is a valid store name counts as a store, so a path like `./a=b.key` is still read as a path.

**Writing commands** (`set`, `rm`, `import`, `rekey`, and the source of `cp-store`/`mv-store`) work on one store and take plain `-k PATH` or `-k -`.

#### What needs a key

| Command | Key needed |
|---|---|
| `ls-store`, `rm-store`, `keygen`, `migrate` | none |
| `create-store` | none for a plain store; a new secret with `-e` (see below) |
| `ls`, `get`, `set`, `rm`, `import`, `export`, `export-shell`, `run` | the key of each encrypted store involved |
| `cp-store`, `mv-store` | the source store's key |
| `rekey` | the old key and a new secret |
| `encrypt` | a new secret |
| `tui` | the key from `ENV_STORE_KEY_<STORE>` or `[keys]` in the project file, or typed in the Unlock dialog when you open an encrypted store |

#### Choosing a new secret

`create-store -e`, `encrypt`, `rekey`, `cp-store` and `mv-store` can set a new secret. A new secret never comes from `ENV_STORE_KEY_<STORE>` or `[keys]`. Give exactly one of:

| Option | Meaning |
|---|---|
| `-k PATH` / `-k -` (create-store) or `--new-key PATH` / `--new-key -` (the others) | use an existing key file |
| `--generate-key PATH` | write a new key file to `PATH` (mode 0600, never overwrites; the folder must exist) |
| `--passphrase` | use a passphrase: read from stdin when piped (one trailing newline ignored), otherwise asked twice at a hidden prompt (`New passphrase: `, `Repeat to confirm: `) |

`envs` never saves a key or passphrase it reads from stdin. After the command succeeds it warns on stderr, because the store cannot be read without that secret:

```console
$ envs keygen - | envs create-store vault -e -k -
Warning: envs does not save this key; keep it, or store 'vault' cannot be read again
created store 'vault'
```

Save the key first (`envs keygen vault.key`, or in your password manager) and pipe it from there.

#### Rules worth knowing

- **stdin is used once per command.** If a value or passphrase comes from stdin, a key cannot come from `-k -` in the same command:

  ```console
  $ printf 'x\n' | envs set -s prod NEWVAR -k -
  Error: stdin can be used only once per command: it is already used for the value of NEWVAR, so it cannot be used for -k -
  ```

- **The tool never stores or caches keys.** No option takes a key or passphrase literally on the command line. In deployments an existing store's key may come from the environment variable `ENV_STORE_KEY_<STORE>` (see [Deployment](deployment.md)).
- **Error messages never contain values, keys or passphrases.**
- Wrong secrets fail with exit code 4:

  ```console
  $ envs ls -v prod -k staging.key
  Error: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified
  $ envs ls -v prod -k missing.key
  Error: cannot read key or passphrase file 'missing.key': No such file or directory
  $ envs ls -v customer-a -k prod.key
  Error: store 'customer-a' uses a passphrase, but a key file was given
  ```

- A key for a plain store is a usage error (exit code 1):

  ```console
  $ envs ls base -k base=prod.key
  Error: store 'base' is not encrypted; it takes no key or passphrase
  ```

#### Keeping secrets safe

- **Put secrets only in encrypted stores.** A plain store is cleartext on disk. This is what `envs/base.json` from the [Quick start](#quick-start) looks like:

  ```console
  $ cat envs/base.json
  {
    "format": 1,
    "encrypted": false,
    "revision": 2,
    "created_at": "2026-11-06T16:47:58.767402Z",
    "updated_at": "2026-11-06T16:47:58.856850Z",
    "variables": {
      "DB_HOST": "localhost",
      "DB_PORT": "5432",
      "LOG_LEVEL": "info"
    }
  }
  ```

  TOML files and SQLite or PostgreSQL rows of a plain store are just as readable.
- **Keep store data out of git.** If your store folder or database file sits in the project (`json://envs`, `sqlite:///envs.db`), add it to `.gitignore` (`envs/`, `envs.db`) unless it holds only values that may be public. Do the same for key files, passphrase files and generated `.env` files.
- **Protect passphrase and value files.** Files such as `pw.txt` or `customer-a.pass` used with `< FILE` below hold a secret in clear text. Create them with `umask 077` (or `chmod 600` them) and delete them once you are done.
- **Watch what you print.** `ls -v`, `get`, `export` and `export-shell` print decrypted values in clear text, to your terminal, its scrollback, or a CI log. `envs keygen -` prints a key the same way. In CI, prefer `envs run`, which hands the values to the command without printing them.

### The project file `.envstore.toml`

A project file saves you from typing the connection, the store list and the key paths every time. Put `.envstore.toml` in your project root (more detail in [configuration.md](configuration.md)):

```toml
connection = "sqlite:///envs.db"
stores = ["base", "dev", "secret"]
ordered_overwrite = true   # optional; false = first store wins

[keys]
secret = "keys/secret.key"
```

Here `envs.db` and `keys/` live inside the project, so add both to `.gitignore` (see [Keeping secrets safe](#keeping-secrets-safe)).

| Key | Type | Meaning |
|---|---|---|
| `connection` | string | Connection string. Relative `json://`, `toml://` and `sqlite:///` paths are relative to the project file's folder, so the file works from any subfolder. Do not put passwords here; use `ENV_STORE_CONNECTION`. |
| `stores` | list of store names | Default load order for `ls`, `get`, `export`, `export-shell` and `run` when you name no stores. Stores you name on the command line **replace** this list. |
| `ordered_overwrite` | boolean | `true` (default) = last store wins, `false` = first store wins. |
| `[keys]` | table: store name = path | Key or passphrase file per store. Relative paths are relative to the project file's folder; `~` is expanded. Paths only, never the key itself. |

With that file in place, from the project root or any subfolder:

```console
$ envs ls -v --source
API_TOKEN=tok-123        secret
DB_HOST=dev.example.com  dev
DB_PORT=5432             base
LOG_LEVEL=info           base
DEBUG=false              dev
$ envs get DB_HOST
dev.example.com
$ envs get DB_HOST --first-wins
localhost
$ envs run -- sh -c 'echo "$DB_HOST $API_TOKEN"'
dev.example.com tok-123
$ envs ls -v base
DB_HOST=localhost
DB_PORT=5432
LOG_LEVEL=info
```

Things to know:

- **Lookup.** `envs` looks for `.envstore.toml` in the current folder, then in each parent folder. The first one found is used.
- **Trust.** The file must belong to you (or root) and must not be writable by every user. Otherwise it is ignored with a warning:

  ```console
  $ envs ls
  Warning: ignoring project file '/home/me/project/.envstore.toml': writable by every user
  Error: no stores given: name stores, or set 'stores' in .envstore.toml
  ```

- **Strict.** Unknown keys and invalid values are errors, for example `unknown key 'foo' (allowed: connection, keys, ordered_overwrite, stores)`.
- **Writing commands never take the store from the file.** `set`, `rm`, `import`, `rekey` and `encrypt` always need `-s STORE`. They do use `connection` and `[keys]` (after `-k` and `ENV_STORE_KEY_<STORE>`).
- **`--no-project`** ignores the file completely:

  ```console
  $ envs --no-project ls base
  Error: no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set 'connection' in .envstore.toml
  ```

- The file is read by every command except `keygen`, `-h`/`--help` and `--version`. A broken project file makes every other command fail until you fix it or pass `--no-project`.

---

## Global options and environment variables

Global options go **before** the command name: `envs --noinput -c json://envs rm-store old -y`. After the command name they are unknown, and the error says where they belong:

```console
$ envs -c json://envs ls --noinput base
Usage: envs ls [OPTIONS] [STORES]...
Try 'envs ls --help' for help.

Error: No such option: --noinput; --noinput is a global option: put it before the command, e.g. envs --noinput ls
```

| Option | Meaning |
|---|---|
| `-c`, `--connection URL` | Connection string. Overrides `ENV_STORE_CONNECTION` and `connection` in the project file. |
| `--no-project` | Ignore `.envstore.toml`. |
| `--noinput` | Never prompt, even at a terminal. A missing key fails with exit code 4; a missing confirmation (no `-y`) fails with exit code 1. Use it in CI and scripts. |
| `--version` | Print the version and exit. |
| `-h`, `--help` | Show help. Every command has its own `-h` / `--help` too: `envs export -h`. |

When stdin is not a terminal (in a pipe or CI), `envs` already behaves as if `--noinput` were set.

| Environment variable | Meaning |
|---|---|
| `ENV_STORE_CONNECTION` | Connection string, used when `-c` is not given. Empty counts as unset. |
| `ENV_STORE_ORDERED_OVERWRITE` | `true` (last store wins) or `false` (first store wins). Also accepts `1`/`0`/`yes`/`no`, any case. Empty counts as unset. |
| `ENV_STORE_KEY_<STORE>` | Key line or passphrase of an existing encrypted store, e.g. `ENV_STORE_KEY_CUSTOMER_A` for `customer-a`. Used when `-k` is not given, before `[keys]` and the prompt. Never used for new keys; `envs run` removes these variables from the command's environment. See [Deployment](deployment.md). |

An invalid value stops every command except `keygen`, which reads no settings:

```console
$ ENV_STORE_ORDERED_OVERWRITE=maybe envs ls
Error: invalid value 'maybe' for ENV_STORE_ORDERED_OVERWRITE: use true/false/1/0/yes/no
```

Running `envs` with no command prints the help and exits with code 1. There is no shell completion.

---

## Commands

The examples in this section use `export ENV_STORE_CONNECTION=json://envs` or `sqlite:///envs.db` unless they show `-c`.

### Stores

#### `envs ls-store` — list stores

```text
envs ls-store [--json]
```

Lists every store and whether it is encrypted. Needs no key.

| Option | Meaning |
|---|---|
| `--json` | Print one JSON document with timestamps and revision numbers. |

```console
$ envs ls-store
name        encryption
base        plain
customer-a  encrypted (passphrase)
prod        encrypted (keyfile)
staging     encrypted (keyfile)
```

The encryption column reads `plain`, `encrypted (keyfile)` or `encrypted (passphrase)`. With no stores at all, `ls-store` prints nothing on stdout (`[]` with `--json`) and exits 0, and stderr names the location it looked at (the absolute folder, the SQLite file, or the PostgreSQL host, database and schema, never the password), so a mistyped connection is easy to spot:

```console
$ envs -c json://emvs ls-store
no stores in /home/me/project/emvs
```

```console
$ envs ls-store --json
[
  {
    "created_at": "2026-11-06T16:37:45.082136Z",
    "encrypted": false,
    "key_mode": null,
    "name": "base",
    "revision": 2,
    "updated_at": "2026-11-06T16:37:45.334610Z"
  },
  {
    "created_at": "2026-11-06T16:37:45.207364Z",
    "encrypted": false,
    "key_mode": null,
    "name": "dev",
    "revision": 6,
    "updated_at": "2026-11-06T16:37:47.743987Z"
  }
]
```

`key_mode` is `"keyfile"`, `"passphrase"` or `null`. Times are UTC. `revision` goes up by one with every write.

#### `envs create-store` — create a store

```text
envs create-store NAME [-e (-k PATH|- | --generate-key PATH | --passphrase)]
```

| Option | Meaning |
|---|---|
| `-e`, `--encrypt` | Create an encrypted store. Needs exactly one of the next three options. |
| `-k`, `--key PATH\|-` | Encrypt with an existing key file (`-` reads it from stdin). |
| `--generate-key PATH` | Encrypt with a new key file written to `PATH` (mode 0600, never overwritten). |
| `--passphrase` | Encrypt with a passphrase: read from stdin when piped, otherwise asked twice. |

```console
$ envs create-store base
created store 'base'
$ envs keygen prod.key
wrote key file 'prod.key'
$ envs create-store prod -e -k prod.key
created store 'prod'
$ envs create-store staging -e --generate-key staging.key
created store 'staging'
$ envs create-store customer-a -e --passphrase < customer-a.pass
Warning: envs does not save this passphrase; keep it, or store 'customer-a' cannot be read again
created store 'customer-a'
```

Common mistakes:

```console
$ envs create-store prod -e -k prod.key
Error: store 'prod' already exists
$ envs create-store bad -k prod.key
Error: -k, --generate-key and --passphrase encrypt the new store: add -e/--encrypt
$ envs create-store bad -e
Error: an encrypted store needs one of -k <path>, --generate-key <path>, --passphrase
```

#### `envs rm-store` — delete a store

```text
envs rm-store NAME [-y]
```

| Option | Meaning |
|---|---|
| `-y`, `--yes` | Do not ask for confirmation. |

Deleting needs no key, also for an encrypted store. At a terminal, `envs` asks `Delete store 'staging'? [y/N]: `; only `y` or `yes` deletes. In scripts, pass `-y`:

```console
$ envs rm-store staging
Error: Delete store 'staging'? Confirm with -y/--yes (no terminal to ask, or --noinput)
$ envs rm-store staging -y
deleted store 'staging'
$ envs rm-store nope -y
Error: store 'nope' not found in /home/me/project/envs.db
```

#### `envs cp-store` and `envs mv-store` — copy, rename, move, decrypt

```text
envs cp-store SRC DST [--to URL] [-k PATH|-] [--plain | --new-key PATH|- | --generate-key PATH | --passphrase]
envs mv-store SRC DST [same options]
```

`cp-store` copies a store under a new name. `mv-store` renames it (a copy followed by a delete; a failure never leaves you with zero copies). With `--to`, the copy goes into another backend, where `DST` may be the same name as `SRC`.

| Option | Meaning |
|---|---|
| `--to URL` | Connection string of the target backend. |
| `-k`, `--key PATH\|-` | Key or passphrase file of the source store. |
| `--plain` | Make an unencrypted copy. This is how you decrypt a store. |
| `--new-key PATH\|-` | Encrypt the copy with this existing key file. |
| `--generate-key PATH` | Encrypt the copy with a new key file written to `PATH`. |
| `--passphrase` | Encrypt the copy with a passphrase. |

By default the copy is encrypted the same way as the source, with the same key.

```console
$ envs cp-store legacy legacy-copy -k legacy.key
copied store 'legacy' to 'legacy-copy'
$ envs cp-store legacy legacy-plain -k legacy.key --plain
copied store 'legacy' to 'legacy-plain'
$ envs cp-store legacy legacy-copy2 -k legacy.key --generate-key copy2.key
copied store 'legacy' to 'legacy-copy2'
$ envs mv-store legacy-copy2 archive -k copy2.key
moved store 'legacy-copy2' to 'archive'
$ envs cp-store base base --to json://backup
copied store 'base' to 'base'
$ envs mv-store legacy-plain legacy-plain --to toml://moved
moved store 'legacy-plain' to 'legacy-plain'
```

Errors:

```console
$ envs cp-store legacy legacy-copy -k legacy.key
Error: store 'legacy-copy' already exists
$ envs cp-store legacy legacy -k legacy.key
Error: store 'legacy' cannot be copied onto itself: choose another name, or another backend with --to
$ envs cp-store legacy x -k legacy.key --plain --generate-key y.key
Error: use only one of --plain, --new-key, --generate-key, --passphrase
```

### Variables

#### `envs ls` — list variables

```text
envs ls [STORES]... [-v] [--source] [--first-wins] [-k STORE=PATH]... [--json]
```

Lists the variable names of one or more stores, merged in load order. With no stores, it uses `stores` from the project file. One store is listed sorted by name; several stores are listed store by store in load order, as described in [Output order](#output-order).

| Option | Meaning |
|---|---|
| `-v`, `--values` | Also show the values. |
| `--source` | Show which store each winning value comes from. |
| `--first-wins` | The first store wins instead of the last. |
| `-k`, `--key STORE=PATH` | Key or passphrase file of a store; `-` reads stdin; repeatable. With one store, `-k PATH` is enough. |
| `--json` | Print one JSON document. |

```console
$ envs ls base
DB_HOST
DB_PORT
LOG_LEVEL
$ envs ls -v base dev
DB_HOST=dev.example.com
DB_PORT=5432
LOG_LEVEL=info
DEBUG=false
$ envs ls -v --source base dev
DB_HOST=dev.example.com  dev
DB_PORT=5432             base
LOG_LEVEL=info           base
DEBUG=false              dev
```

Values that do not fit on one line are shown as JSON strings, for example `MULTI="a\nb"`. Missing stores are all named in one error (exit code 2):

```console
$ envs ls base nope missing
Error: store 'nope' not found in /home/me/project/envs; store 'missing' not found in /home/me/project/envs
```

#### `envs get` — print one value

```text
envs get NAME [STORES]... [--first-wins] [-k STORE=PATH]... [--json]
```

Prints the value of one variable. With several stores, it prints the value that wins.

| Option | Meaning |
|---|---|
| `--first-wins` | The first store wins instead of the last. |
| `-k`, `--key STORE=PATH` | Key or passphrase file of a store; repeatable. |
| `--json` | Print `name`, `value` and the winning `store` as JSON. |

The raw value is printed **without a trailing newline** unless stdout is a terminal, so `$(envs get NAME store)` returns the value exactly, multi-line values included.

```console
$ envs get DB_HOST base dev
dev.example.com
$ envs get DB_HOST base dev --first-wins
localhost
$ envs get --json DB_HOST base dev
{
  "name": "DB_HOST",
  "store": "dev",
  "value": "dev.example.com"
}
$ envs get NOPE base dev
Error: variable 'NOPE' not found in stores 'base', 'dev'
```

Use it in a script:

```sh
db_password="$(envs get DB_PASSWORD prod -k prod.key)"
```

#### `envs set` — set variables

```text
envs set -s STORE KEY=VALUE... [-o] [-k PATH|-]
envs set -s STORE KEY [-o] [-k PATH|-]        # value from stdin or a hidden prompt
```

| Option | Meaning |
|---|---|
| `-s`, `--store STORE` | The store to change (required). |
| `-o`, `--overwrite` | Replace variables that already exist. |
| `-k`, `--key PATH\|-` | Key or passphrase file of the store. |

All pairs are written in one step. The value is everything after the first `=` and may be empty.

```console
$ envs set -s base DB_HOST=localhost DB_PORT=5432 LOG_LEVEL=info
set DB_HOST, DB_PORT, LOG_LEVEL in store 'base'
$ envs set -s dev 'GREETING=hello world' EMPTY=
set GREETING, EMPTY in store 'dev'
$ envs set -s dev DEBUG=true
Error: variables already exist in store 'dev': DEBUG; use -o/--overwrite to replace them
$ envs set -s dev -o DEBUG=true
set DEBUG in store 'dev'
```

**Secrets: one name, value on stdin.** For an encrypted store, `KEY=VALUE` pairs are refused, because command lines end up in your shell history:

```console
$ envs set -s prod DB_PASSWORD=hunter2 -k prod.key
Error: store 'prod' is encrypted: values on the command line end up in the shell history; give one name and pipe its value on stdin (envs set -s prod NAME < FILE) or type it at the hidden prompt (envs set -s prod NAME)
```

Give one name instead. The value is read from stdin when it is piped. At a terminal you are asked twice at a hidden prompt (`Value of DB_PASSWORD: `, `Repeat to confirm: `); if the two entries differ, `envs` says `values do not match` and asks again, up to three attempts.

```console
$ envs set -s prod DB_PASSWORD -k prod.key < pw.txt
set DB_PASSWORD in store 'prod'
$ printf 'db.prod.internal' | envs set -s prod DB_HOST -k prod.key
set DB_HOST in store 'prod'
```

Exactly one trailing newline (LF or CRLF) is removed from stdin. To store a value that ends in a newline, use [`import`](#envs-import--fill-a-store-from-a-file). The one-name form works for plain stores too.

Empty stdin is an error, so a forgotten pipe (or `< /dev/null` in CI) never blanks a variable. To set an empty value on purpose, send just a newline, or use `KEY=` for a plain store:

```console
$ envs set -s prod -o DB_PASSWORD -k prod.key < /dev/null
Error: no value was read from stdin (it was empty); to set an empty value, send a newline (echo | envs set -s prod DB_PASSWORD) or, for a plain store, use envs set -s prod DB_PASSWORD=
$ echo | envs set -s prod -o DB_PASSWORD -k prod.key
set DB_PASSWORD in store 'prod'
```

#### `envs rm` — delete variables

```text
envs rm -s STORE NAME... [-k PATH|-]
```

| Option | Meaning |
|---|---|
| `-s`, `--store STORE` | The store to change (required). |
| `-k`, `--key PATH\|-` | Key or passphrase file of the store. |

Deletes in one step, without asking. If any name is missing, nothing is deleted:

```console
$ envs rm -s dev GREETING EMPTY
removed GREETING, EMPTY from store 'dev'
$ envs rm -s dev NOPE X
Error: variables not found in store 'dev': NOPE, X
```

#### `envs import` — fill a store from a file

```text
envs import -s STORE [-f PATH|-] [-t dotenv|json|toml] [-o] [-k PATH|-]
```

| Option | Meaning |
|---|---|
| `-s`, `--store STORE` | The store to fill (required; it must exist). |
| `-f`, `--file PATH\|-` | Input file. `-` or no `-f` reads stdin. |
| `-t`, `--type dotenv\|json\|toml` | File format. Inferred from the file name when omitted; stdin defaults to dotenv. |
| `-o`, `--overwrite` | Replace variables that already exist. |
| `-k`, `--key PATH\|-` | Key or passphrase file of the store. |

Given this `app.env`:

```sh
# comment
export API_URL=https://api.example.com
NAME="Jane Doe"   # inline comment
GREETING='hello ${USER}'
MULTI="a\nb"
EMPTY=
```

```console
$ envs import -s app -f app.env
imported 5 variables into store 'app'
$ envs ls -v app
API_URL=https://api.example.com
EMPTY=
GREETING=hello ${USER}
MULTI="a\nb"
NAME=Jane Doe
```

dotenv input is read literally: `${USER}` is **never** expanded. Comments, `export` prefixes, single and double quotes, escapes in double quotes (`\n`, `\t`, ...), and CRLF line ends are understood. If a name repeats, the last value counts.

JSON and TOML input must be a flat object of string values:

```console
$ envs import -s app -f flags.json
imported 2 variables into store 'app'
$ printf 'X = "y"\n' | envs import -s app -t toml
imported 1 variable into store 'app'
$ printf '' | envs import -s app
nothing to import into store 'app'
```

Errors:

```console
$ envs import -s app -f app.env
Error: variables already exist in store 'app': API_URL, NAME, GREETING, MULTI, EMPTY; use -o/--overwrite to replace them
$ envs import -s app -f nested.json
Error: JSON input has a nested object under 'A'; nested input (e.g. a --nested export) is refused, import a flat object of string values instead
$ envs import -s app -f num.json
Error: JSON value of 'A' must be a string, got int
$ printf 'A="unterminated\n' | envs import -s dev
Error: invalid dotenv input at line 1: unterminated double-quoted value
```

How file names map to formats (for `import -f` and `export -f`):

| File name | Format |
|---|---|
| ends in `.json` (any case) | JSON |
| ends in `.toml` (any case) | TOML |
| starts with `.env` (`.env`, `.env.local`, `.env.production`) or ends in `.env` | dotenv |
| anything else | error, pass `-t` |

`.json` and `.toml` win, so `.env.json` is JSON.

### Export and run

#### `envs export` — write dotenv, JSON or TOML

```text
envs export [STORES]... [-f PATH|-] [-t dotenv|json|toml] [--force] [--nested] [--first-wins] [-k STORE=PATH]...
```

| Option | Meaning |
|---|---|
| `-f`, `--file PATH\|-` | Output file. `-` or no `-f` writes to stdout. |
| `-t`, `--type dotenv\|json\|toml` | Format. Inferred from the file name; stdout defaults to dotenv. |
| `--force` | Replace an existing output file. |
| `--nested` | Keep stores apart: one table per store (JSON, TOML) or `STORE__NAME` (dotenv). |
| `--first-wins` | The first store wins instead of the last. |
| `-k`, `--key STORE=PATH` | Key or passphrase file of a store; repeatable. |

The variables come out in the merged [output order](#output-order): `base`'s variables sorted by name, then the ones `dev` adds. `DB_HOST` keeps its place from `base` but has `dev`'s value.

```console
$ envs export base dev
DB_HOST=dev.example.com
DB_PORT=5432
LOG_LEVEL=info
DEBUG=false
$ envs export -t json base dev
{
  "DB_HOST": "dev.example.com",
  "DB_PORT": "5432",
  "LOG_LEVEL": "info",
  "DEBUG": "false"
}
$ envs export -t toml base dev
DB_HOST = "dev.example.com"
DB_PORT = "5432"
LOG_LEVEL = "info"
DEBUG = "false"
```

Nested output:

```console
$ envs export --nested base dev
BASE__DB_HOST=localhost
BASE__DB_PORT=5432
BASE__LOG_LEVEL=info
DEV__DB_HOST=dev.example.com
DEV__DEBUG=false
$ envs export --nested -t json base dev
{
  "base": {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "LOG_LEVEL": "info"
  },
  "dev": {
    "DB_HOST": "dev.example.com",
    "DEBUG": "false"
  }
}
$ envs export --nested -t toml base dev
[base]
DB_HOST = "localhost"
DB_PORT = "5432"
LOG_LEVEL = "info"

[dev]
DB_HOST = "dev.example.com"
DEBUG = "false"
```

**Writing a file.** Output files are created with mode 0600. An existing file is replaced only with `--force`. If the export fails, no file is left behind.

```console
$ envs export base dev -f .env
exported to '.env'
$ ls -l .env
-rw-------  1 me  staff  64 Nov  6 17:38 .env
$ envs export base dev -f .env
Error: output file '.env' already exists; use --force to replace it
$ envs export base dev -f .env --force
exported to '.env'
$ envs export base dev -f config.yaml
Error: cannot infer the format of 'config.yaml' from its name: pass -t dotenv, -t json or -t toml
```

**How dotenv values are quoted.** The output reads back exactly with both python-dotenv and Docker Compose. Here is a store `quoting` with some tricky values:

```console
$ envs create-store quoting
created store 'quoting'
$ envs set -s quoting PLAIN=abc_1.2:3@x 'SPACE=hello world' 'DOLLAR=pa$$word' "SQ=it's" 'BS=C:\temp' 'TWO_BS=a\\b' EMPTY= $'MULTI=line 1\nline 2'
set PLAIN, SPACE, DOLLAR, SQ, BS, TWO_BS, EMPTY, MULTI in store 'quoting'
$ envs export quoting
BS='C:\temp'
DOLLAR='pa$$word'
EMPTY=''
MULTI="line 1\nline 2"
PLAIN=abc_1.2:3@x
SPACE='hello world'
SQ="it's"
TWO_BS="a\\\\b"
```

- Simple values (letters, digits and `_ . / : @ % + , -`) are written bare.
- Other values go in single quotes when possible. A single backslash, as in `C:\temp`, stays in single quotes.
- Values with a newline or carriage return, `'`, two backslashes in a row, or a trailing backslash go in double quotes with escapes.

Two kinds of value cannot be written to dotenv safely, and the export stops with exit code 1:

- any value containing `${`;
- a value that needs double quotes and contains `$`.

```console
$ envs set -s quoting 'GREETING=hello ${USER}'
set GREETING in store 'quoting'
$ envs export quoting
Error: the value of 'GREETING' cannot be written to a dotenv file that python-dotenv and Docker Compose both read back exactly: it contains '${', which python-dotenv interpolates even in single quotes; export with -t json or -t toml, or use envs run instead
```

Use `-t json`, `-t toml` or `envs run` for such values. The same happens to `app` from the [import example](#envs-import--fill-a-store-from-a-file), which also holds `GREETING='hello ${USER}'`.

#### `envs export-shell` — load stores into your shell

```text
eval "$(envs export-shell [STORES]... [-o] [--nested] [--first-wins] [-k STORE=PATH]...)"
```

| Option | Meaning |
|---|---|
| `-o`, `--overwrite` | Replace variables already set in the shell. |
| `--nested` | Prefix each variable with its store name: `STORE__NAME`. |
| `--first-wins` | The first store wins instead of the last. |
| `-k`, `--key STORE=PATH` | Key or passphrase file of a store; repeatable. |

It prints shell statements. By default, a variable already set in your shell (even to an empty string) is kept:

```console
$ envs export-shell base dev
[ -n "${DB_HOST+x}" ] || export DB_HOST=dev.example.com
[ -n "${DB_PORT+x}" ] || export DB_PORT=5432
[ -n "${LOG_LEVEL+x}" ] || export LOG_LEVEL=info
[ -n "${DEBUG+x}" ] || export DEBUG=false
$ envs export-shell -o base dev
export DB_HOST=dev.example.com
export DB_PORT=5432
export LOG_LEVEL=info
export DEBUG=false
```

Values are quoted for the shell, so spaces, quotes and newlines are safe. It works in POSIX shells (bash, zsh, dash). For fish or PowerShell, use [`envs run`](#envs-run--run-a-command-with-the-variables).

#### `envs run` — run a command with the variables

```text
envs run [STORES]... [-o] [--nested] [--first-wins] [-k STORE=PATH]... -- COMMAND [ARGS]...
```

| Option | Meaning |
|---|---|
| `-o`, `--overwrite` | Replace variables already set in the environment. |
| `--nested` | Prefix each variable with its store name: `STORE__NAME`. |
| `--first-wins` | The first store wins instead of the last. |
| `-k`, `--key STORE=PATH` | Key or passphrase file of a store; repeatable. |

Everything after `--` is the command. It runs directly, without a shell, with the store variables **added** to the current environment. Variables that are already set win unless you pass `-o`. Every `ENV_STORE_KEY_*` variable is removed, so the command never inherits a key.

```console
$ envs run base dev -- sh -c 'echo "$DB_HOST $DEBUG"'
dev.example.com false
$ DB_HOST=preset envs run base dev -- sh -c 'echo "$DB_HOST"'
preset
$ DB_HOST=preset envs run -o base dev -- sh -c 'echo "$DB_HOST"'
dev.example.com
```

The exit code is the command's own. On Linux and macOS, `envs` replaces itself with the command, so signals such as Ctrl-C go straight to it.

```console
$ envs run base -- sh -c 'exit 7'; echo $?
7
$ envs run base -- doesnotexist
Error: cannot run 'doesnotexist': No such file or directory        # exit code 127
$ envs run base -- ./noexec.sh
Error: cannot run './noexec.sh': Permission denied                 # exit code 126
$ envs run base
Error: run needs a command after '--': envs run [STORES]... -- CMD [ARGS]...
```

### Keys and encryption commands

#### `envs keygen` — create a key file

```text
envs keygen PATH|-
```

Writes a new random key file (mode 0600). It never overwrites a file. `envs keygen -` prints the key instead, for example to paste into a password manager or a CI secret. `keygen` reads neither the connection nor the project file, so it works without a connection and even with a broken `.envstore.toml`.

```console
$ envs keygen prod.key
wrote key file 'prod.key'
$ ls -l prod.key
-rw-------  1 me  staff  60 Nov  6 17:37 prod.key
$ envs keygen prod.key
Error: key file 'prod.key' already exists; refusing to overwrite it
$ envs keygen -
envstore-key-v1:musZTANLkul-ohKsHvAzAWjKtit9usfPPX-wfLQfwfo
```

Keep key files out of version control. Back them up: without the key, an encrypted store cannot be read.

#### `envs encrypt` — encrypt a plain store

```text
envs encrypt -s STORE (--new-key PATH|- | --generate-key PATH | --passphrase)
```

| Option | Meaning |
|---|---|
| `-s`, `--store STORE` | The store to encrypt (required). |
| `--new-key PATH\|-` | Use an existing key file. |
| `--generate-key PATH` | Write a new key file to `PATH`. |
| `--passphrase` | Use a passphrase: from stdin when piped, otherwise asked twice. |

```console
$ envs encrypt -s legacy --generate-key legacy.key
encrypted store 'legacy' (keyfile)
$ envs encrypt -s legacy --new-key legacy.key
Error: store 'legacy' is already encrypted: use 'envs rekey -s legacy'
```

There is no `decrypt` command. To get a plain version, make a plain copy with `envs cp-store SRC DST --plain`.

#### `envs rekey` — change a store's key

```text
envs rekey -s STORE [-k PATH|-] (--new-key PATH|- | --generate-key PATH | --passphrase)
```

| Option | Meaning |
|---|---|
| `-s`, `--store STORE` | The store to re-encrypt (required). |
| `-k`, `--key PATH\|-` | The current key or passphrase file. Without it, the current key comes from `ENV_STORE_KEY_<STORE>`, `[keys]` or the prompt. |
| `--new-key PATH\|-` | Switch to an existing key file. |
| `--generate-key PATH` | Switch to a new key file written to `PATH`. |
| `--passphrase` | Switch to a passphrase (a new salt is used every time). |

`rekey` can switch between key file and passphrase in either direction. Afterwards only the new secret works. In the example below, the new passphrase is read from the file `prod.pass` (created with `umask 077`, so only you can read it), and the file is deleted at the end. Never write the passphrase itself into the command line, for example with `printf ... |`: it would end up in your shell history. Without `< prod.pass`, `rekey --passphrase` asks for it twice at a hidden prompt.

```console
$ envs rekey -s prod -k prod.key --generate-key prod-2026.key
rekeyed store 'prod' (keyfile)
$ envs ls prod -k prod.key
Error: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified
$ envs rekey -s prod -k prod-2026.key --passphrase < prod.pass
Warning: envs does not save this passphrase; keep it, or store 'prod' cannot be read again
rekeyed store 'prod' (passphrase)
$ envs rekey -s prod -k prod.pass --new-key prod-2026.key
rekeyed store 'prod' (keyfile)
$ rm prod.pass
$ envs rekey -s prod -k prod-2026.key
Error: give the new secret: --new-key, --generate-key or --passphrase
$ envs rekey -s base --new-key prod.key
Error: store 'base' is not encrypted: use 'envs encrypt -s base'
```

### Terminal UI: `tui`

```text
envs tui
```

Needs the `tui` extra. The full guide is [tui.md](tui.md). It opens a full-screen browser for your stores, using the same connection, project file and `[keys]` as every other command. In the TUI you can view, add, edit and delete variables. Creating, copying, importing, exporting and key changes stay on the command line.

| Screen | Keys |
|---|---|
| Stores | arrows to move, **Enter** open, **r** reload, **q** quit |
| Unlock (for an encrypted store without a usable `[keys]` entry) | enter a key or passphrase file path, or type the passphrase; **Enter** unlock, **Esc** cancel |
| Variables (values masked as `••••••••`) | **v** show/hide values, **a** add, **e** or **Enter** edit, **d** delete (asks first), **r** reload, **Esc** back |
| Add / Edit | **Ctrl+S** save, **Esc** cancel |
| Confirm | **y** yes, **n** or **Esc** no |

The key you type in the Unlock dialog is forgotten when you leave the store. If someone else changed the store in the meantime, nothing is written and the TUI offers to reload.

The TUI needs a real terminal:

```console
$ envs tui < /dev/null
Error: envs tui needs a terminal: stdin and stdout must not be redirected
$ envs --noinput tui
Error: envs tui is interactive and cannot run with --noinput
```

### Database schema: `migrate`

```text
envs migrate
```

Creates or upgrades the SQL schema (SQLite and PostgreSQL). File backends have no schema.

```console
$ envs -c sqlite:///envs.db migrate
created schema v1
$ envs -c sqlite:///envs.db migrate
schema is up to date (v1)
$ envs -c json://x migrate
Error: the 'json' backend has no schema to migrate
```

After an upgrade it prints `upgraded schema from vN to vM`.

You rarely need it with SQLite, which creates and upgrades its schema on its own. With PostgreSQL you need it in two cases: first setup when your normal database user lacks the `CREATE` privilege (an admin runs it once), and after upgrading Environment Store to a version with a newer schema.

What happens when `envs` connects to a database:

| Database state | SQLite | PostgreSQL |
|---|---|---|
| missing or empty | schema created | schema created |
| current schema | used | used |
| older schema | upgraded automatically | refused: run `envs migrate` |
| newer schema (from a newer Environment Store) | refused | refused |
| other tables, not ours | refused | refused |

A refusal exits with code 1 and writes nothing.

---

## Output modes

| Command | Default | `-v` | `--source` | `--json` |
|---|---|---|---|---|
| `ls-store` | table: name, encryption | | | list of objects: `name`, `encrypted`, `key_mode`, `revision`, `created_at`, `updated_at` |
| `ls` | variable names | `NAME=value` | adds the winning store as a column | list of objects with `name`, plus `value` with `-v` and `store` with `--source` |
| `get` | the raw value (no trailing newline unless at a terminal) | | | object with `name`, `value`, `store` |

```console
$ envs ls --json -v --source base dev
[
  {
    "name": "DB_HOST",
    "store": "dev",
    "value": "dev.example.com"
  },
  {
    "name": "DB_PORT",
    "store": "base",
    "value": "5432"
  },
  {
    "name": "LOG_LEVEL",
    "store": "base",
    "value": "info"
  },
  {
    "name": "DEBUG",
    "store": "dev",
    "value": "false"
  }
]
```

Each JSON object has sorted keys, the list itself follows the [output order](#output-order), and the indentation is 2 spaces, so it is easy to diff and to read with `jq`. Status messages and errors always go to stderr, so piping stdout gives you clean data.

---

## Exit codes

| Code | Meaning | Examples |
|---|---|---|
| 0 | Success | |
| 1 | Usage, validation or configuration error; backend error; missing extra; refused confirmation | bad store name, no connection, `-k` for a plain store, unknown option, `rm-store` without `-y` in a script |
| 2 | Not found | store or variable does not exist |
| 3 | Already exists | `create-store` on an existing store, `set` without `-o` on an existing variable |
| 4 | Key or decryption problem | no key given, wrong key, unreadable key file, key file for a passphrase store |
| 5 | Someone else changed the store at the same moment. Nothing was written; run the command again | |
| 126 | `run` only: the command exists but cannot be run | `Permission denied` |
| 127 | `run` only: the command was not found | |
| any | `run` only: the command's own exit code | |

Every error ends with one line, `Error: <message>`, on stderr. Usage errors found while reading the command line (an unknown option, a missing `-s`) first print the usage line, a `Try ... --help` hint and a blank line:

```console
$ envs ls --bogus
Usage: envs ls [OPTIONS] [STORES]...
Try 'envs ls --help' for help.

Error: No such option: --bogus
```

Some usage errors add a hint after `;`: a global option after the command name (see [Global options](#global-options-and-environment-variables)), or a missing `-s` while the project file sets `stores`:

```console
$ envs set A=1
Usage: envs set [OPTIONS] {KEY=VALUE... | KEY}
Try 'envs set --help' for help.

Error: Missing option '-s' / '--store'. writing commands never take the store from the project file's 'stores'; name it with -s STORE
```

If you parse stderr in a script, read the last line.

---

## Recipes

### Layer a base store with an environment store

Keep shared defaults in `base` and the differences per environment in `dev`, `staging` and `prod`. List the specific store **last**, so it wins:

```console
$ envs ls -v --source base dev
DB_HOST=dev.example.com  dev
DB_PORT=5432             base
LOG_LEVEL=info           base
DEBUG=false              dev
```

For prod, encrypt the store and bind its key:

```console
$ envs ls -v --source base prod -k prod=prod.key
DB_HOST=db.prod.internal  prod
DB_PORT=5432              base
LOG_LEVEL=info            base
DB_PASSWORD=hunter2       prod
```

To make the layering the default for a project, put it in `.envstore.toml`:

```toml
connection = "sqlite:///envs.db"
stores = ["base", "dev"]
```

Now `envs ls -v`, `envs run -- ...` and `envs export` use `base` then `dev`. Name stores on the command line to use a different list for one command, for example `envs run base prod -k prod=prod.key -- ./deploy.sh`.

### Run your app with the variables: `envs run -- python app.py`

```sh
envs run base dev -- python app.py
```

`app.py` sees `DB_HOST`, `DB_PORT` and the rest in `os.environ`. Nothing is written to disk, and values containing `$`, `${...}` or newlines arrive unchanged. Verified with a one-line Python program:

```console
$ envs run base dev -- python3 -c 'import os; print(os.environ["DB_HOST"])'
dev.example.com
```

Variables you set yourself still win, which is handy for a quick override:

```console
$ DB_HOST=preset envs run base dev -- sh -c 'echo "$DB_HOST"'
preset
```

### Load stores into your current shell

```sh
eval "$(envs export-shell base dev)"
```

```console
$ eval "$(envs export-shell base dev)"; echo "$DB_HOST:$DB_PORT"
dev.example.com:5432
```

Already-set variables are kept; add `-o` to replace them. Key prompts go to stderr, so this also works with an encrypted store when you are at a terminal: `eval "$(envs export-shell base prod)"` asks for prod's key and then loads the variables.

### Generate a `.env` file for Docker Compose

```console
$ envs export base dev -f .env --force
exported to '.env'
$ cat .env
DB_HOST=dev.example.com
DB_PORT=5432
LOG_LEVEL=info
DEBUG=false
```

The file is created with mode 0600. Docker Compose reads `.env` from the project folder for `${VAR}` substitution in `compose.yaml`, or you can pass it to a service:

```yaml
services:
  app:
    image: my-app
    env_file: .env
```

The quoting is chosen so Docker Compose and python-dotenv read every value back exactly. Values that cannot be written that way (anything with `${`, or `$` together with a newline or carriage return, `'`, two backslashes in a row, or a trailing backslash) make the export fail instead of producing a wrong file. Remember to add `.env` to `.gitignore`. (The Docker Compose side of this recipe was not run for this guide.)

### CI: no prompts, key from a secret

In CI, store the key line (from `envs keygen -`) as a secret, pipe it to `envs`, and pass `--noinput` so a missing key fails fast instead of waiting for input:

```console
$ printf '%s\n' "$PROD_KEY" | envs --noinput run base prod -k prod=- -- sh -c 'echo "$DB_HOST ${#DB_PASSWORD}"'
db.prod.internal 7
```

The command prints the length of the password, not the password, so the value never reaches the CI log. For a passphrase store, the secret holds the passphrase; the command is the same.

Or name the secret `ENV_STORE_KEY_PROD`: `envs` then reads it without `-k`, and `envs run` removes it from the environment of the command it starts. This also works with several encrypted stores, one variable each. See [Deploying with encrypted stores](deployment.md#other-containers-and-ci).

GitHub Actions example:

```yaml
- name: Deploy
  env:
    ENV_STORE_CONNECTION: ${{ secrets.ENV_STORE_CONNECTION }}
    PROD_KEY: ${{ secrets.PROD_KEY }}
  run: printf '%s\n' "$PROD_KEY" | envs --noinput run base prod -k prod=- -- ./deploy.sh
```

If the key is missing, the step stops with exit code 4:

```console
$ envs --noinput run base prod -- true
Error: store 'prod' is encrypted and no key or passphrase was given: pass it with -k prod=<path> (or -k prod=- for stdin), or set ENV_STORE_KEY_PROD
```

stdin can feed only one key per command. With two encrypted stores, write one key to a temporary file (with `umask 077`) and pass it with `-k store=PATH`:

```console
$ envs ls base prod -k base=- -k prod=-
Error: only one -k may read from stdin ('-'); stdin can be read once
```

### Rotate a key

Re-encrypt the store with a fresh key file, then replace the old file everywhere it is used:

```console
$ envs rekey -s prod -k prod.key --generate-key prod-2026.key
rekeyed store 'prod' (keyfile)
$ envs ls prod -k prod-2026.key
DB_HOST
DB_PASSWORD
$ envs ls prod -k prod.key
Error: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified
```

Then update `[keys]` in `.envstore.toml`, the CI secrets and every `ENV_STORE_KEY_PROD` of your deployments ([rotation in a deployment](deployment.md#security-notes)), and delete the old key file. To switch to a passphrase instead, use `--passphrase`; to switch back to a key file, use `--new-key` or `--generate-key`.

### Encrypt an existing plain store

```console
$ envs ls-store
name        encryption
base        plain
legacy      plain
$ envs encrypt -s legacy --generate-key legacy.key
encrypted store 'legacy' (keyfile)
$ envs ls -v legacy -k legacy.key
API_KEY=abc123
API_URL=https://api.example.com
```

Add `legacy = "legacy.key"` to the `[keys]` table of your project file so you do not need `-k` every time. If you ever need a plain version again, make a plain copy: `envs cp-store legacy legacy-plain -k legacy.key --plain`.

### Back up or move stores to another backend

```console
$ envs -c sqlite:///envs.db cp-store base base --to json://backup
copied store 'base' to 'base'
$ envs -c sqlite:///envs.db mv-store legacy-plain legacy-plain --to toml://moved
moved store 'legacy-plain' to 'legacy-plain'
```

Encrypted stores stay encrypted with the same key unless you choose `--plain` or a new secret.

---

## Reference pages: man and tldr

Besides `envs -h`, two reference pages ship with the project:

| Page | In the repository | What it is |
|---|---|---|
| man page `envs(1)` | [`docs/man/share/man/man1/envs.1`](man/share/man/man1/envs.1) | every command and option, global options, exit codes, environment variables, the project file and the merge order. `environment-store(1)` is the same page. |
| tldr page | [`docs/tldr/envs.md`](tldr/envs.md) | eight common examples in the [tldr-pages](https://github.com/tldr-pages/tldr) format |

**The man page.** The wheel installs it as `share/man/man1/envs.1` under the environment's prefix. Where that prefix's `bin` is on your `PATH`, `man envs` finds it, for example in an activated virtual environment after `uv pip install 'environment-store[cli]'` or `pip install 'environment-store[cli]'`, or with `uv run` in a project (`uv run man envs`).

`uv tool install` is different: uv links only the executables into `~/.local/bin`, not the man page, so plain `man envs` finds nothing. The page is still inside the tool's environment, which `uv tool dir` names. Open it by path, or add the directory to `MANPATH` (the trailing `:` keeps the system man pages):

```sh
man "$(uv tool dir)/environment-store/share/man/man1/envs.1"
export MANPATH="$(uv tool dir)/environment-store/share/man:"   # then: man envs
```

From a clone of the repository, `man docs/man/share/man/man1/envs.1` works without installing anything.

**The tldr page** is not in the tldr-pages project yet (it has not been submitted), so `tldr envs` does not find it. Read [`docs/tldr/envs.md`](tldr/envs.md) directly, or render it with a client that accepts a file, for example `tldr --render docs/tldr/envs.md` (checked with tealdeer; other clients have similar options).

---

## Troubleshooting

| Message | What to do |
|---|---|
| `no connection configured` | Pass `-c`, set `ENV_STORE_CONNECTION`, or add `connection` to `.envstore.toml`. |
| `No such option: --noinput` (or `-c`, `--no-project`) | Global options go before the command: `envs --noinput ls ...`. |
| `no stores given` | Name the stores, or set `stores` in `.envstore.toml`. Check for a warning that the project file was ignored. |
| `Missing option '-s' / '--store'` | Writing commands (`set`, `rm`, `import`, `encrypt`, `rekey`) always need `-s STORE`. |
| `-k <path> without a store name works with exactly one store` | Use `-k STORE=PATH` with several stores. |
| `store 'x' is encrypted: values on the command line end up in the shell history` | Pipe the value: `envs set -s x NAME < file`. |
| `cannot be written to a dotenv file` | Export with `-t json` or `-t toml`, or use `envs run`. |
| `no stores in <location>` | The backend at that location is empty. If you expected stores, check the connection for a typo. |
| `no value was read from stdin (it was empty)` | `set` got nothing on stdin. Pipe the value; for an empty value, pipe a newline (`echo \| envs set ...`) or use `KEY=`. |
| `uses a passphrase, but a key file was given` | Pass the passphrase file with `-k`, or switch the store to a key file with `envs rekey -s STORE --new-key PATH`. |
| `ignoring project file ...: writable by every user` | `chmod o-w .envstore.toml`. |
| exit code 5 | Another process changed the store at the same time. Nothing was written; run the command again. |
