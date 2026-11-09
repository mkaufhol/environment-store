# Configuration

This page covers everything you can configure: where your stores live (the **connection string**), the
environment variables the tool reads, the project file `.envstore.toml`, and the rules for store names, variable
names and values.

Every command on this page was run against the real CLI, unless it talks to PostgreSQL. Those examples follow the
code and were not run.

- [Choose a backend: connection strings](#choose-a-backend-connection-strings)
- [What the stored data looks like](#what-the-stored-data-looks-like)
- [Upgrade the SQL schema: `envs migrate`](#upgrade-the-sql-schema-envs-migrate)
- [Environment variables](#environment-variables)
- [The project file `.envstore.toml`](#the-project-file-envstoretoml)
- [Which setting wins](#which-setting-wins)
- [Names and values](#names-and-values)

## Choose a backend: connection strings

A connection string tells `envs` where your stores live. There is no default: you always give one, in one of
three ways (see [Which setting wins](#which-setting-wins)):

```console
$ envs -c json://envs ls-store                     # 1. on the command line (-c / --connection)
$ export ENV_STORE_CONNECTION=json://envs          # 2. in the environment
$ echo 'connection = "json://envs"' > .envstore.toml   # 3. in the project file
```

`-c` is a global option, so it goes **before** the command name: `envs -c json://envs ls-store`, not
`envs ls-store -c json://envs`.
The second form fails and says so:

```console
$ envs ls-store -c json://envs
Usage: envs ls-store [OPTIONS]
Try 'envs ls-store -h' for help.

Error: No such option: -c; -c is a global option: put it before the command, e.g. envs -c URL ls-store
```

Without any of them, a command that needs a store fails with exit code 1:

```console
$ envs ls-store
Error: no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set 'connection' in .envstore.toml
```

`envs keygen`, `envs completion`, `envs -h` / `envs --help` and `envs --version` work without a connection. They do not read the project file
either, so a broken `.envstore.toml` cannot stop them.

A connection with a typo in the path is not an error: it simply points at an empty backend. `ls-store` then says on
stderr where it looked, with the resolved location (an absolute directory, a database file, or the PostgreSQL schema,
database and host, never the password):

```console
$ envs -c json://emvs ls-store
no stores in /home/me/project/emvs
$ envs -c postgresql://envs:secret@db.example.com/app ls-store
no stores in schema 'environment_store' of database 'app' on host 'db.example.com'
```

stdout stays empty (`[]` with `--json`) and the exit code is 0, so scripts are not affected.

### Overview

| Backend | Connection string | Install | Good for |
|---|---|---|---|
| JSON files | `json://envs` | included | one person, one machine; files you can read and diff |
| TOML files | `toml://envs` | included | the same, if you prefer TOML |
| SQLite | `sqlite:///envs.db` | included | one file holding all stores |
| PostgreSQL | `postgresql://user@host/db` | the `postgres` extra: `uv tool install 'environment-store[cli,postgres]'` (pip: `pip install 'environment-store[cli,postgres]'`) | a team or several machines sharing stores |

### JSON and TOML files

Each store is one file in a directory: `<store>.json` or `<store>.toml`.

| You write | Directory used |
|---|---|
| `json://envs` | `envs` relative to the current directory |
| `json:///srv/envs` | the absolute path `/srv/envs` (three slashes) |
| `json://~/envs` | `envs` in your home directory (`~` is expanded) |

`toml://` works the same way. A missing directory is created on the first write, with mode `0700` (only you can
open it); store files get mode `0600`. Reading never creates anything. A query string or fragment is refused:

```console
$ envs -c 'json://envs?x=1' ls-store
Error: a json:// connection string takes no query or fragment ('?', '#'); name only the directory, e.g. json://envs
```

A JSON directory ignores `.toml` files and vice versa, so one directory can in principle hold both, but it is
clearer to keep them apart.

### SQLite

All stores live in one database file.

| You write | Database file |
|---|---|
| `sqlite:///envs.db` | `envs.db` relative to the current directory (three slashes) |
| `sqlite:///data/envs.db` | `data/envs.db` relative to the current directory |
| `sqlite:////home/me/envs.db` | the absolute path `/home/me/envs.db` (four slashes) |
| `sqlite:///~/data/envs.db` | `data/envs.db` in your home directory (`~` is expanded) |

Things to know:

- The paths follow the same rules as `json://` and `toml://`: `~` is expanded, and a missing parent directory is
  created on the first write with mode `0700`. The database file (and its `-wal` and `-shm` files) gets mode `0600`.
  Reading an absent database creates nothing:

  ```console
  $ envs -c sqlite:///~/data/envs.db ls-store
  no stores in /home/me/data/envs.db
  $ envs -c sqlite:///~/data/envs.db create-store base
  created store 'base'
  $ ls -ld ~/data ~/data/envs.db
  drwx------  3 me  staff     96 Nov  6 19:27 /home/me/data
  -rw-------  1 me  staff  20480 Nov  6 19:27 /home/me/data/envs.db
  ```

- A host, query or fragment is refused:

  ```console
  $ envs -c sqlite://host/x.db ls-store
  Error: a SQLite connection string must name a database file: sqlite:///relative.db or sqlite:////absolute/path.db (no host, query or fragment)
  ```

- The tables are created on first use and upgraded automatically when you install a newer version.
  You never need `envs migrate` for SQLite, though it works.

### PostgreSQL

Install the extra first: `uv tool install 'environment-store[cli,postgres]'` for the CLI, `uv add
'environment-store[postgres]'` for the library, or `pip install 'environment-store[cli,postgres]'`
(see [Installation](installation.md#optional-extras)). Without it you get
`Error: this feature needs the optional 'postgres' dependencies: uv add 'environment-store[postgres]' (or pip install 'environment-store[postgres]'); for the CLI tool: uv tool install 'environment-store[cli,postgres]'`.

```text
postgresql://user@host:5432/dbname
postgres://user@host/dbname
postgresql://user@host/dbname?schema=team_a
postgresql://user@host/dbname?sslmode=require
```

- Both `postgresql://` and `postgres://` work.
- All tables live in their **own PostgreSQL schema**, `environment_store` by default. Nothing else in the database
  is touched, so you can use a database that other applications also use.
- `?schema=<name>` picks another schema. This lets several independent environment stores share one database.
  The name must match `^[a-z_][a-z0-9_]{0,62}$` (lowercase letters, digits, `_`). The `schema` parameter is
  removed before the string reaches the driver.
- Every other parameter (`sslmode`, `connect_timeout`, …) is passed unchanged to libpq, PostgreSQL's client
  library. libpq's usual mechanisms, such as `~/.pgpass` and `PGPASSWORD`, work too.
- In the user name and password, percent-encode `@`, `/` and `?` as `%40`, `%2F` and `%3F`. For example, the
  password `p@ss` is written `postgresql://app:p%40ss@db.example.com/app`.
- **Keep passwords out of the project file.** Put a connection string with a password in `ENV_STORE_CONNECTION`
  (for example from your CI secret store). `envs` never prints the password in a message.

**First setup.** On first use, `envs` creates the schema and its tables if they are missing or empty. That needs
the `CREATE` privilege. If the database user does not have it, the command fails with a hint. A database
administrator then runs this once with a privileged user:

```console
$ envs -c postgresql://admin@db.example.com/app migrate
created schema v1
```

**Upgrades.** Unlike SQLite, PostgreSQL schemas are **not** upgraded automatically, because several machines may
use the same database with different versions of `envs`. After upgrading environment-store, run `envs migrate` once.
Until then, commands are refused with a hint to run it.

### What happens when `envs` connects to a database

| What it finds | SQLite | PostgreSQL |
|---|---|---|
| Nothing, or an empty file / schema | creates the tables | creates the schema and tables |
| Its own tables, same version | uses them | uses them |
| Its own tables, older version | upgrades them automatically | refuses: run `envs migrate` |
| Its own tables, newer version | refuses: upgrade environment-store | refuses: upgrade environment-store |
| Tables that are not its own | refuses | refuses |

Every refusal exits with code 1 and writes nothing. `envs` recognises its own tables by a row
`('app', 'environment-store')` in its `meta` table, so it never takes over a database that holds something else.

### Wrong connection strings

```console
$ envs -c envs ls-store
Error: a connection string must start with 'scheme://', e.g. json://path/to/dir, sqlite:///envs.db or postgresql://host/db
$ envs -c redis://x ls-store
Error: unsupported connection scheme 'redis': use one of json, postgres, postgresql, sqlite, toml
$ envs -c "" ls-store
Error: the connection option (-c/--connection) must not be empty
```

All of these exit with code 1.

## What the stored data looks like

You never need to edit these files or tables by hand, but it helps to know what is in them.

### Files

After creating a plain store `base` and an encrypted store `prod` with `json://envs`:

```console
$ ls -la envs
-rw-------  .base.json.lock
-rw-------  .prod.json.lock
-rw-------  base.json
-rw-------  prod.json
```

- One file per store; the file name is the store name.
- Files are created with mode `0600` (only you can read them).
- The hidden `.lock` files coordinate concurrent writers. Leave them alone.
- Writes are atomic: the new content is written to a temporary file and then moved into place.

A plain store (`envs/base.json`):

```json
{
  "format": 1,
  "encrypted": false,
  "revision": 2,
  "created_at": "2026-11-06T16:37:41.256910Z",
  "updated_at": "2026-11-06T16:37:41.372048Z",
  "variables": {
    "DB_HOST": "localhost",
    "DB_PORT": "5432"
  }
}
```

An encrypted store (`envs/prod.json`). The variable names and values are inside `payload`:

```json
{
  "format": 1,
  "encrypted": true,
  "revision": 2,
  "created_at": "2026-11-06T16:37:41.495584Z",
  "updated_at": "2026-11-06T16:37:41.618057Z",
  "payload": "oa3k2TCI6Tcx3+F7q4lOhkBQF7/+dXYmy/EdoQtEZH3BW5v0goljuzeyZ4ax0DQLK3U/DuWYZ7VKGfJoiy/x8ppPhA==",
  "cipher": {
    "name": "aes256gcm",
    "mode": "keyfile"
  }
}
```

The same plain store in TOML (`toml://cfg`, `cfg/base.toml`):

```toml
format = 1
encrypted = false
revision = 2
created_at = 2026-11-06T16:37:41.758323Z
updated_at = 2026-11-06T16:37:41.882832Z

[variables]
A = "1"
```

`revision` goes up by one with every write. If two processes change the same store at the same moment, the second
write is refused with exit code 5 and nothing is lost: just run the command again.

### SQL tables

SQLite and PostgreSQL use the same two tables. This is the SQLite version (`sqlite3 envs.db .schema`):

```sql
CREATE TABLE meta (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE stores (
    name        TEXT NOT NULL PRIMARY KEY,
    encrypted   BOOLEAN NOT NULL CHECK (encrypted IN (0, 1)),
    cipher_meta TEXT,
    variables   TEXT,
    ciphertext  BLOB,
    revision    INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    CHECK (
        (encrypted AND cipher_meta IS NOT NULL AND ciphertext IS NOT NULL AND variables IS NULL)
        OR
        (NOT encrypted AND cipher_meta IS NULL AND variables IS NOT NULL AND ciphertext IS NULL)
    )
);
```

- One row per store. A plain store keeps its variables as one JSON object in `variables`; an encrypted store keeps
  them in `ciphertext`.
- On PostgreSQL the columns are `JSONB`, `BYTEA` and `TIMESTAMPTZ`, and both tables live in the dedicated schema.
- `meta` holds `('app', 'environment-store')` and `('schema_version', '1')`.

## Upgrade the SQL schema: `envs migrate`

`envs migrate` creates the tables, or upgrades them to the version your installed environment-store expects.

```console
$ envs -c sqlite:///data/envs.db migrate      # new database
created schema v1
$ envs -c sqlite:///envs.db migrate           # nothing to do
schema is up to date (v1)
```

After an upgrade it prints `upgraded schema from vN to vM`.

| Backend | When you need it |
|---|---|
| SQLite | never; it creates and upgrades automatically. Running it is harmless. |
| PostgreSQL | after upgrading environment-store, and for the first setup when the normal user lacks `CREATE` |
| JSON, TOML | never; there is no schema. `envs migrate` fails with `Error: the 'json' backend has no schema to migrate` |

## Environment variables

`envs` reads these environment variables. Keys and passphrases come from the environment, `ENV_STORE_KEY_<STORE>` or
`ENV_STORE_LOAD`, only for existing stores, never for new ones (see [Encryption and keys](encryption.md) and
[Deployment](deployment.md)).

| Variable | Meaning | Values |
|---|---|---|
| `ENV_STORE_CONNECTION` | the connection string | any connection string; empty counts as unset |
| `ENV_STORE_ORDERED_OVERWRITE` | merge order when you read several stores | `true` (default): the last store wins. `false`: the first store wins. Also `1/0/yes/no`, any case. Empty counts as unset |
| `ENV_STORE_KEY_<STORE>` | the key or passphrase of an existing encrypted store: the store name in upper case, `-` as `_`, e.g. `ENV_STORE_KEY_CUSTOMER_A` for `customer-a` | the key line (`envstore-key-v1:…`, not base64-encoded) or the passphrase; one trailing newline removed. `-k` wins over it, it wins over `[keys]`. Empty or invalid is an error (exit code 4). Ignored for plain stores and for stores the command does not use; never used for new keys; `envs run` removes it from the command's environment |
| `ENV_STORE_LOAD` | a load specification: the stores to load, in load order, and the key or passphrase of every encrypted one. Print it with [`envs export-credentials`](deployment.md#two-variables-for-everything-env_store_load) | one line, `envstore-load-v1:` and URL-safe base64; treat it as opaque and as secret as all its keys together. Its stores are the default store list of the reading commands and of `load()` when no stores are named; its keys rank like `ENV_STORE_KEY_<STORE>`, and an encrypted store with a key in both is an error (exit code 1) unless `-k` gives its key. Its keys of plain stores and of stores the command does not use are ignored. Empty counts as unset; invalid is an error (exit code 1); `envs run` removes it from the command's environment |

A typical CI setup:

```sh
export ENV_STORE_CONNECTION='postgresql://ci:…@db.internal/app?schema=team_a'
envs --noinput run base prod -k prod=/run/secrets/prod.key -- ./deploy.sh
```

Where no key file can be shipped, as on Heroku, set `ENV_STORE_KEY_PROD` to the content of the key file instead and
drop the `-k`. Or replace everything but the connection with one variable: `ENV_STORE_LOAD` names the stores and holds
their keys, so `envs --noinput run -- ./deploy.sh` is enough
([Two variables for everything](deployment.md#two-variables-for-everything-env_store_load)).
[Deploying with encrypted stores](deployment.md) covers Heroku, Kubernetes, containers and CI, and what encryption
protects when the key and the connection live in the same configuration.

An invalid value fails every command except `keygen` and `completion` (exit code 1). The message for
`ENV_STORE_LOAD` says what is wrong but never shows the value, because it holds keys:

```console
$ ENV_STORE_ORDERED_OVERWRITE=maybe envs ls-store
Error: invalid value 'maybe' for ENV_STORE_ORDERED_OVERWRITE: use true/false/1/0/yes/no
$ ENV_STORE_LOAD=garbage envs ls-store
Error: ENV_STORE_LOAD is not a valid load specification: it must start with 'envstore-load-v1:'
```

## The project file `.envstore.toml`

A project file saves you from typing the connection, the store list and the key paths every time. Put it in your
project's root directory:

```toml
connection = "json://envs"
stores = ["base", "prod"]
ordered_overwrite = true

[keys]
prod = "keys/prod.key"
```

Now, from the project directory or any subdirectory:

```console
$ cd sub/deeper
$ envs ls -v --source
DB_HOST=localhost    base
DB_PORT=5432         base
DB_PASSWORD=hunter2  prod
$ envs get DB_PASSWORD
hunter2
```

### Keys

| Key | Type | What it does |
|---|---|---|
| `connection` | string | The connection string. Relative `json://`, `toml://` and `sqlite:///` paths are resolved from the **project file's directory**, not the current directory, so the file works from any subdirectory. Absolute paths, `~` paths and PostgreSQL strings are used as written |
| `stores` | list of store names | The default load order for the reading commands `ls`, `get`, `export`, `export-shell`, `run` and `export-credentials`. Stores you name on the command line **replace** this list; they are not added to it. The stores of `ENV_STORE_LOAD` replace it too |
| `ordered_overwrite` | `true` / `false` | `true` (default): the last store wins. `false`: the first store wins |
| `[keys]` | table: store name → path | The key file or passphrase file for each encrypted store. Relative paths are resolved from the project file's directory; `~` is expanded. A key-file line (`envstore-key-v1:…`) is refused; any other text is taken as a path, so never put a passphrase here, only the path of a passphrase file |

Any other key is an error, so typos do not go unnoticed:

```console
$ envs ls-store
Error: project file '/…/.envstore.toml': unknown key 'foo' (allowed: connection, keys, ordered_overwrite, stores)
```

Other errors you may see (all exit code 1; messages never repeat the values in the file):

```text
Error: project file '/…/.envstore.toml' is not valid TOML
Error: project file '/…/.envstore.toml': 'ordered_overwrite' must be true or false
Error: project file '/…/.envstore.toml': 'stores' must be a list of store names (lowercase letters, digits, '_', '-', starting with a letter)
Error: project file '/…/.envstore.toml': [keys] entry for store 'prod' holds key material: paths only, never key material
Error: [keys] in '/…/.envstore.toml' names a key for store 'base', which is not encrypted: remove the entry
```

The last one appears when a command loads that plain store, and that includes every write to it: `set`, `rm` and
`import` on the store all fail until you remove the entry. So add a `[keys]` entry only **after** you have encrypted
the store, and update it after `envs rekey` (see [Encryption and keys](encryption.md#in-the-project-file-keys)).

> [!WARNING]
> Only a key-file line (`envstore-key-v1:…`) in `[keys]` is detected and refused. Any other text, including a
> passphrase, is treated as a file path, and the error for a missing file prints that path. With
> `[keys] dev = "correct horse battery staple"`, `envs ls dev` fails with exit code 4 and shows the passphrase on
> stderr:
>
> ```text
> Error: cannot read key or passphrase file '/…/correct horse battery staple': No such file or directory
> ```
>
> Put the passphrase in a file (mode `0600`, outside the repository) and list the path of that file.

A broken project file makes every command fail except `envs keygen`, `envs completion`, `envs -h` / `--help` and `envs --version`, which do not
read it. Use `--no-project` to work around it, or fix the file.

### Writing commands do not use `stores`

`set`, `rm`, `import`, `rekey` and `encrypt` change exactly one store, and you always name it with `-s`. They never
pick it from the `stores` list. They all use `connection`. `set`, `rm`, `import` and `rekey` also take the store's
current key from `[keys]`, unless `-k` or the environment (`ENV_STORE_KEY_<STORE>`, `ENV_STORE_LOAD`) gives it. The
store list of `ENV_STORE_LOAD` does not pick their store either. `encrypt` does not read `[keys]` at all: you give the new key with `--new-key`,
`--generate-key` or `--passphrase`.

```sh
envs set -s base LOG_LEVEL=debug
```

### How the file is found

`envs` looks for `.envstore.toml` in the current directory, then in each parent directory up to `/`. It uses the
first regular file it finds and stops looking, even if that file is then ignored by the trust check below.

To ignore the project file for one command, pass `--no-project` (before the command name):

```console
$ envs --no-project ls base
Error: no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set 'connection' in .envstore.toml
```

### The trust check

Because the project file can point `envs` at key files and databases, it must be trustworthy. On Linux and macOS,
the file is used only if:

- it is owned by you or by root, and
- it is not writable by every user (group-writable is fine).

A symbolic link owned by another user is never followed. An untrusted file is ignored with a warning, and the
command carries on as if there were no project file:

```console
$ chmod o+w .envstore.toml
$ envs ls-store
Warning: ignoring project file '/…/.envstore.toml': writable by every user
Error: no connection configured: pass -c/--connection, set ENV_STORE_CONNECTION, or set 'connection' in .envstore.toml
```

The other reasons are `owned by another user` and `a symbolic link owned by another user`. Fix it with
`chmod o-w .envstore.toml` or by taking ownership of the file.

### Do not put passwords in the project file

The project file is usually committed. If its `connection` contains a password (in the URL or as a `password` or
`sslpassword` parameter), every command that reads the file warns:

```console
$ envs ls-store
Warning: the connection in project file '/…/.envstore.toml' contains a password; credentials should not be stored in a file that may be committed: set ENV_STORE_CONNECTION instead
name  encryption
base  plain
```

The command still runs. Move the connection string to `ENV_STORE_CONNECTION`, or use a password-less connection
string and let libpq find the password in `~/.pgpass`.

The same goes for keys: commit the `[keys]` **paths** if you like, but never the key files themselves. Add them to
`.gitignore`.

## Which setting wins

| Setting | Highest priority first |
|---|---|
| Connection | `-c` / `--connection` → `ENV_STORE_CONNECTION` → `connection` in `.envstore.toml` → error |
| Store list (reading commands) | stores named on the command line → the stores of `ENV_STORE_LOAD` → `stores` in `.envstore.toml` → error |
| Merge order (which value wins) | `--first-wins` → `ENV_STORE_ORDERED_OVERWRITE` → `ordered_overwrite` → last store wins |
| Key of an existing encrypted store | `-k` → the environment: `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD` (a key in both is an error, exit code 1) → `[keys]` in `.envstore.toml` → hidden prompt on a terminal → error, exit code 4 |
| New secret (`create-store -e`, `encrypt`, `rekey`, `cp-store` / `mv-store`) | only the command's own options (`-k`, `--new-key`, `--generate-key`, `--passphrase`); never the environment or `[keys]` |

For example, with `connection = "json://envs"` in the project file, `ENV_STORE_CONNECTION=json://elsewhere` makes
`envs` use `elsewhere`, and `-c json://other` beats both.

There is no `--last-wins` flag: "last wins" is the default, and `--first-wins` is the only override on the command
line.

With no store named, no `ENV_STORE_LOAD` and no `stores` in the project file:

```console
$ envs ls
Error: no stores given: name stores, set ENV_STORE_LOAD, or set 'stores' in .envstore.toml
```

## Names and values

### Store names

A store name is 1 to 63 characters: lowercase letters, digits, `_` and `-`, **starting with a letter**.

```text
^[a-z][a-z0-9_-]{0,62}$
```

| Valid | Invalid |
|---|---|
| `dev`, `prod`, `base`, `customer-a`, `team_b`, `app2` | `Prod` (uppercase), `1abc` (starts with a digit), `-x`, `my.store`, `""` |

```console
$ envs -c json://envs create-store 1abc
Error: invalid store name '1abc': use 1 to 63 lowercase letters, digits, '_' or '-', starting with a letter (^[a-z][a-z0-9_-]{0,62}$)
```

Why these rules? Store names become file names, and in nested mode (`--nested`) they become part of shell variable
names: the store name is upper-cased and `-` becomes `_`, so `customer-a` plus `DB_HOST` gives
`CUSTOMER_A__DB_HOST`. Because a store name starts with a letter, that is always a valid shell variable name. The same
rule names a store's key variable: `customer-a` reads its key from `ENV_STORE_KEY_CUSTOMER_A`. So `my-app` and
`my_app` share `ENV_STORE_KEY_MY_APP`; a command that uses both while they are encrypted and the variable is set stops
with exit code 1, unless `-k` gives both keys.

Two store names that differ only in `-` versus `_` (`customer-a` and `customer_a`) are both allowed, but they
produce the same prefix. Loading both in nested dotenv, shell or `run` output is an error as soon as both stores
define the same variable name:

```console
$ envs -c json://envs export --nested customer-a customer_a
Error: nested key CUSTOMER_A__X is produced by both X in store 'customer-a' and X in store 'customer_a'; rename one of them or export without nested mode
```

Nested JSON and TOML export keep the two stores apart (one table per store), so they still work. Avoid such pairs.

### Variable names

Variable names follow POSIX environment variable rules: letters, digits and `_`, not starting with a digit. They
are case-sensitive, so `db_host` and `DB_HOST` are two different variables.

```text
^[A-Za-z_][A-Za-z0-9_]*$
```

```console
$ envs -c json://envs set -s customer-a 9BAD=x
Error: invalid variable name '9BAD': use letters, digits and '_', not starting with a digit (^[A-Za-z_][A-Za-z0-9_]*$)
```

A single store is listed sorted by variable name. Several stores are listed store by store in load order, each sorted by name, with a variable that several stores define at its first position ([output order](cli.md#output-order)).

### Values

A value can be any UTF-8 text:

- empty: `EMPTY=`
- with spaces or any punctuation: `'GREETING=hello world'` (quote it for the shell)
- multi-line: pipe it in, or import it from a file

```console
$ envs -c json://envs set -s customer-a EMPTY= 'GREETING=hello world'
set EMPTY, GREETING in store 'customer-a'
$ printf 'line1\nline2\n' | envs -c json://envs set -s customer-a MULTI
set MULTI in store 'customer-a'
$ envs -c json://envs ls -v customer-a
EMPTY=
GREETING=hello world
MULTI="line1\nline2"
```

`ls -v` shows a value with a newline or tab as a JSON string, so each variable stays on one line. `envs get` prints
the raw value.

When a value comes from stdin, exactly one trailing newline is removed (`printf 'line1\nline2\n'` stores
`line1\nline2`). To store a value that really ends in a newline, import it from a file and write the newline as
`\n` inside double quotes (a plain `NAME=value` line never keeps one, because its newline just ends the line):

```console
$ printf 'TRAILING="ends in a newline\\n"\n' > values.env
$ cat values.env
TRAILING="ends in a newline\n"
$ envs -c json://envs import -s customer-a -f values.env
imported 1 variable into store 'customer-a'
$ envs -c json://envs ls -v customer-a
EMPTY=
GREETING=hello world
MULTI="line1\nline2"
TRAILING="ends in a newline\n"
```

A JSON file works too: `{"TRAILING": "ends in a newline\n"}`.

Two things are refused, because an environment variable cannot hold them:

- the NUL character:

  ```console
  $ printf 'a\0b' | envs -c json://envs set -s customer-a NUL
  Error: value of variable 'NUL' contains a NUL character, which environment variables cannot hold
  ```

- text that is not valid UTF-8 (lone surrogates, in Python terms).

## See also

- [Encryption and keys](encryption.md): encrypted stores, key files, passphrases and `[keys]`.
- [CLI reference](cli.md): every command and option.
- [Python library](python.md): the same settings from Python (`load()`, `EnvironmentStore`).
