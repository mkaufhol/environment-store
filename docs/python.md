# Using Environment Store from Python

<img src="assets/environment-store-logo.svg" alt="Environment Store logo" width="96" align="right">

Environment Store keeps environment variables in named **stores**, optionally encrypted, in a
backend of your choice: a folder of JSON or TOML files, a SQLite file, or PostgreSQL. This page
shows how to use it from Python code. The command line tool `envs` is described in
[cli.md](cli.md); both work on the same stores, so you can create stores with the CLI and read
them from Python, or the other way round.

All examples on this page were run top to bottom against one scratch SQLite database, starting
with [the setup below](#set-up-the-example-stores), and the output shown is the real output.

- [Install](#install)
- [Concepts in two minutes](#concepts-in-two-minutes)
- [Set up the example stores](#set-up-the-example-stores)
- [Keep secrets out of version control](#keep-secrets-out-of-version-control)
- [How do I load my stores into `os.environ` at startup?](#how-do-i-load-my-stores-into-osenviron-at-startup)
- [How do I read one value?](#how-do-i-read-one-value)
- [How do I write a `.env`, JSON or TOML file?](#how-do-i-write-a-env-json-or-toml-file)
- [How do I manage stores from a script?](#how-do-i-manage-stores-from-a-script)
- [How do I work with encrypted stores?](#how-do-i-work-with-encrypted-stores)
- [How do I use an encrypted store in CI?](#how-do-i-use-an-encrypted-store-in-ci)
- [How do I deploy with two environment variables?](#how-do-i-deploy-with-two-environment-variables)
- [Which errors should I catch?](#which-errors-should-i-catch)
- [Typing notes](#typing-notes)
- [API reference](#api-reference)

## Install

The library needs Python 3.12 or newer. In a uv project, add it with `uv add` and run your code
with `uv run`; with pip, install it into your virtual environment:

```sh
uv add environment-store                     # library, encryption, JSON, TOML and SQLite
uv add 'environment-store[postgres]'         # adds the PostgreSQL backend (psycopg)
uv add 'environment-store[all]'              # library, PostgreSQL, CLI and TUI
uv run python app.py                         # run your code in the project's environment

pip install environment-store                # the same with pip
pip install 'environment-store[postgres]'
```

[Installation](installation.md#optional-extras) explains every extra and the pip equivalents.

If you open a `postgresql://` connection without the `postgres` extra, you get a
`MissingExtraError` whose message names the command to run: `uv add 'environment-store[postgres]'`,
or `pip install 'environment-store[postgres]'` with pip.

## Concepts in two minutes

- A **store** is a named set of variables (name to string value), such as `base`, `dev`,
  `prod` or `customer-a`. Store names are 1 to 63 characters: lowercase letters, digits, `_`
  and `-`, and they start with a letter.
- Variable names follow POSIX rules: letters, digits and `_`, not starting with a digit
  (`DB_HOST`, `_private`). They are case-sensitive. Values are any UTF-8 text except the NUL
  character, including empty and multi-line values.
- A store is either plaintext or **encrypted** as a whole (AES-256-GCM). An encrypted store has a
  **key file** (a random key, created with `generate_key_file()` or `envs keygen`) or a
  **passphrase**.
- A **connection string** picks the backend:

  | Backend | Connection string |
  |---|---|
  | JSON files (one file per store) | `json://envs` (relative), `json:///abs/dir`, `json://~/envs` |
  | TOML files (one file per store) | `toml://envs`, `toml:///abs/dir`, `toml://~/envs` |
  | SQLite | `sqlite:///envs.db` (relative), `sqlite:////abs/path/envs.db` (four slashes), `sqlite:///~/envs.db` |
  | PostgreSQL | `postgresql://user@host:5432/db`, optional `?schema=name` (default `environment_store`) |

  A relative path in `connection=`, `EnvironmentStore(...)` or `ENV_STORE_CONNECTION` is
  relative to the **current directory** of the process. If your application starts from another
  directory, loading looks for the stores there and fails with `StoreNotFoundError`, which names
  the path it looked at. For applications, use an absolute path or put the connection in the
  [project file](#configure-it-once-outside-your-code), where relative paths are relative to the
  file.

  `~` is expanded for `json://`, `toml://` and `sqlite:///`. A missing directory (the store
  directory, or the database file's directory) is created on the first write with mode `0700`;
  store files and the database get mode `0600`. Reading never creates a file or directory. The
  SQLite database is set up on the first write, a PostgreSQL schema on first use. Put database
  passwords in the `ENV_STORE_CONNECTION` environment variable, never in a file you commit.
- When you load several stores, they are merged **in order, and the last store wins** for a
  variable that appears in more than one. `first_wins=True` reverses that. The merged result
  lists the variables store by store in load order, each store's names sorted; see
  [the order of the merged variables](#the-order-of-the-merged-variables).

## Set up the example stores

The examples below use three stores: `base`, `dev` and an encrypted `prod`. This script creates
them in `envs.db` in the current directory (the CLI equivalent is in [quickstart.md](quickstart.md)):

```python
from pathlib import Path
from environment_store import EnvironmentStore, generate_key_file

with EnvironmentStore("sqlite:///envs.db") as es:
    es.create_store("base")
    es.set_many("base", {"DB_HOST": "localhost", "DB_PORT": "5432", "LOG_LEVEL": "info"})
    es.create_store("dev")
    es.set_many("dev", {"DB_HOST": "dev.example.com", "DEBUG": "true"})

    generate_key_file("prod.key")
    es.create_store("prod", encrypt=True, key=Path("prod.key"))
    es.set("prod", "DB_PASSWORD", "hunter2", key=Path("prod.key"))

    for info in es.list_stores():
        print(info.name, info.encrypted, info.key_mode, info.revision)
```

```text
base False None 2
dev False None 2
prod True keyfile 2
```

To keep the examples short, `prod.key` sits in the current directory. In a real project, keep it
outside the repository, as described next.

## Keep secrets out of version control

- **Never commit key files or passphrase files** (`prod.key`, `customer-a.pass`). Anyone with the
  key and a copy of the store can read the secrets. Best keep them outside the project, for
  example in `~/.config/envstore/`, and point to them from `[keys]` in `.envstore.toml` (see
  [below](#configure-it-once-outside-your-code)). If they must live in the project directory,
  add them to `.gitignore`.
- **Never commit exported files.** `to_file(".env")` or `to_file("settings.json")` writes the
  decrypted values in plain text. Add them to `.gitignore` as well:

  ```gitignore
  *.key
  *.pass
  .env
  .env.*
  ```

- When the stores hold secrets, prefer `environment_store.load()` or `env.apply()` (or
  `envs run` on the command line) over writing a `.env` file: the values then only live in the
  process environment.
- Put database passwords in `ENV_STORE_CONNECTION`, never in `.envstore.toml`.

More on keys and passphrases: [encryption.md](encryption.md).

## How do I load my stores into `os.environ` at startup?

Call `environment_store.load()` once, early, the way you would call `load_dotenv()`:

```python
import os
import environment_store

env = environment_store.load("base", "dev", connection="sqlite:///envs.db")
print(os.environ["DB_HOST"])
print(env.variables())
```

```text
dev.example.com
{'DB_HOST': 'dev.example.com', 'DB_PORT': '5432', 'LOG_LEVEL': 'info', 'DEBUG': 'true'}
```

`base` has `DB_HOST=localhost` and `dev` has `DB_HOST=dev.example.com`; `dev` comes last, so it
wins. `load()` returns an [`Environment`](#environment) that you can inspect or export, and it
has already copied the variables into `os.environ`.

**Variables that are already set are kept.** That way a value from the shell or from your
deployment platform always beats the store. Pass `overwrite=True` to replace them:

```python
os.environ["DB_HOST"] = "from-shell"
environment_store.load("base", "dev", connection="sqlite:///envs.db")
print(os.environ["DB_HOST"])  # from-shell
environment_store.load("base", "dev", connection="sqlite:///envs.db", overwrite=True)
print(os.environ["DB_HOST"])  # dev.example.com
```

### Configure it once, outside your code

`load()` resolves its settings exactly like the CLI, so you rarely need to pass anything:

| Setting | Taken from, in order |
|---|---|
| Connection | `connection=` argument, then `ENV_STORE_CONNECTION`, then `connection` in `.envstore.toml` |
| Stores | the positional arguments, then the stores of `ENV_STORE_LOAD`, then `stores` in `.envstore.toml` |
| Keys | `keys=` argument, then `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD`, then `[keys]` in `.envstore.toml`, then a hidden prompt (terminal only) |
| Merge order | `first_wins=True`, then `ENV_STORE_ORDERED_OVERWRITE`, then `ordered_overwrite` in `.envstore.toml`, then last wins |

For the merge order setting, `true` (the default) means the last store wins and `false` means
the first store wins. `ENV_STORE_ORDERED_OVERWRITE` also accepts `1/0` and `yes/no`. Note that
`first_wins=False` is simply the default, not an override: if the environment or the project
file says `false`, the first store wins even though you did not pass `first_wins=True`.

A project file `.envstore.toml` is looked up in the current directory and its parents. With
this file in the project root:

```toml
connection = "sqlite:///envs.db"
stores = ["base", "dev", "prod"]

[keys]
prod = "~/.config/envstore/prod.key"
```

your application needs one line, and it works from any subdirectory, because relative paths in
the project file are relative to the file itself. `~` is expanded in `[keys]`, so the key can
live outside the project (here the `prod.key` from the setup, moved to `~/.config/envstore/`),
where it cannot be committed by accident:

```python
# src/app/main.py
import os
import environment_store

environment_store.load()
print(os.environ["DB_HOST"], os.environ["DB_PASSWORD"])
```

```text
$ cd src/app && python main.py
dev.example.com hunter2
```

Pass `use_project=False` to ignore the project file. The file format and its trust rules are
described in [cli.md](cli.md).

### Other `load()` options

| Argument | Default | Meaning |
|---|---|---|
| `*stores` | none | Stores in load order; none means the stores of `ENV_STORE_LOAD`, else `stores` from `.envstore.toml` |
| `connection` | `None` | Connection string; `None` uses `ENV_STORE_CONNECTION`, then the project file |
| `keys` | `None` | `{store name: key}`; see [keys](#how-do-i-work-with-encrypted-stores) |
| `first_wins` | `False` | The first store wins instead of the last |
| `overwrite` | `False` | Replace variables already in `os.environ` |
| `nested` | `False` | Do not merge; set `STORE__NAME` variables instead (see below) |
| `use_project` | `True` | `False` ignores `.envstore.toml` |
| `noinput` | `False` | Never prompt for a key, even on a terminal |

With `nested=True` every variable is prefixed with its store name in upper case, with `-`
replaced by `_`: `DB_HOST` from `customer-a` becomes `CUSTOMER_A__DB_HOST`. Nothing is merged.

If no stores are named anywhere, `load()` raises `ConfigurationError`:

```text
ConfigurationError: no stores to load: name them, e.g. load('base_conf'), set ENV_STORE_LOAD, or set 'stores' in .envstore.toml
```

`ENV_STORE_LOAD` holds the stores and their keys in one value; see
[How do I deploy with two environment variables?](#how-do-i-deploy-with-two-environment-variables).

## How do I read one value?

Open an `EnvironmentStore` and use `get()`. Use it as a context manager so the connection is
closed:

```python
from environment_store import EnvironmentStore

with EnvironmentStore("sqlite:///envs.db") as es:
    print(es.get("base", "DB_PORT"))
    print(es.variables("dev"))
```

```text
5432
{'DB_HOST': 'dev.example.com', 'DEBUG': 'true'}
```

To get the value that wins across several stores, load them and look it up. `with_sources()`
also tells you where each value came from, as `(value, store)`:

```python
with EnvironmentStore("sqlite:///envs.db") as es:
    env = es.load(["base", "dev"])
print(env.variables()["DB_HOST"])
print(env.with_sources())
```

```text
dev.example.com
{'DB_HOST': ('dev.example.com', 'dev'), 'DB_PORT': ('5432', 'base'), 'LOG_LEVEL': ('info', 'base'), 'DEBUG': ('true', 'dev')}
```

`es.load()` only reads; it does not touch `os.environ`. Call `env.apply()` if you want that.
To pick the merge order, pass `order=MergeOrder.FIRST_WINS`.

### The order of the merged variables

`Environment.variables()`, `with_sources()`, `apply()`, `dumps()` and `to_file()` list the
variables **store by store, in load order**. Within one store the names are sorted. A variable
that several stores define stays where it first appears and takes the value the merge order
picks. Above, `base` gives `DB_HOST`, `DB_PORT`, `LOG_LEVEL`, then `dev` adds `DEBUG`; `DB_HOST`
keeps its first place with `dev`'s value. Another example, with `store-a` holding
`ENV=development` and `DEBUG=True`, and `store-b` holding `ENV=staging` and `DB_NAME=test`:

```python
from environment_store import EnvironmentStore, MergeOrder

with EnvironmentStore("sqlite:///envs.db") as es:
    print(es.load(["store-a", "store-b"]).variables())
    print(es.load(["store-a", "store-b"], order=MergeOrder.FIRST_WINS).variables())
```

```text
{'DEBUG': 'True', 'ENV': 'staging', 'DB_NAME': 'test'}
{'DEBUG': 'True', 'ENV': 'development', 'DB_NAME': 'test'}
```

`store-a`'s names come first, sorted (`DEBUG`, `ENV`); `store-b` adds `DB_NAME` at the end, and
its `ENV` changes the value but not the position. A single store's variables
(`es.variables("dev")`) are sorted by name. The CLI prints the same order.

To open the backend named by `ENV_STORE_CONNECTION` (and nothing else; no project file), use
`EnvironmentStore.from_env()`:

```python
with EnvironmentStore.from_env() as es:
    ...
```

If the variable is not set, it raises
`ConfigurationError: no connection configured: set ENV_STORE_CONNECTION`.

## How do I write a `.env`, JSON or TOML file?

An `Environment` can serialize itself with `dumps()` or write a file with `to_file()`:

```python
with EnvironmentStore("sqlite:///envs.db") as es:
    env = es.load(["base", "dev"])

env.to_file(".env")  # format from the name: dotenv
env.to_file("settings.json")  # JSON
env.to_file("config.yaml", fmt="json")  # the name says nothing: give fmt
print(env.dumps("dotenv"), end="")
```

```text
DB_HOST=dev.example.com
DB_PORT=5432
LOG_LEVEL=info
DEBUG=true
```

Things to know:

- Files are created with mode `0600` (only you can read them), but their content is plain
  text, including the values of encrypted stores. Do not commit them; see
  [Keep secrets out of version control](#keep-secrets-out-of-version-control).
- An existing file is not replaced unless you pass `force=True`. Without it you get
  `ValidationError: output file '.env' already exists; pass force=True to replace it`.
- The format is inferred from the name: `.json`, `.toml`, and names that start or end with
  `.env` (`.env`, `.env.local`, `prod.env`). Anything else needs `fmt=` (`"dotenv"`, `"json"`,
  `"toml"`, or the `Format` enum).
- `nested=True` keeps the stores apart: one table per store in JSON and TOML, `STORE__NAME`
  in dotenv.

```python
print(env.dumps("toml", nested=True), end="")
```

```text
[base]
DB_HOST = "localhost"
DB_PORT = "5432"
LOG_LEVEL = "info"

[dev]
DB_HOST = "dev.example.com"
DEBUG = "true"
```

The dotenv writer only produces files that python-dotenv and Docker Compose both read back
exactly. A value that cannot be written that way is refused, and no file is written. The most
common case is a value containing `${`:

```text
ValidationError: the value of 'TEMPLATE' cannot be written to a dotenv file that python-dotenv and Docker Compose both read back exactly: it contains '${', which python-dotenv interpolates even in single quotes; export with fmt='json' or fmt='toml', or set the variables with Environment.apply() instead
```

So use `fmt="json"` or `fmt="toml"` for such values, or apply them directly with
`env.apply()`.

## How do I manage stores from a script?

Every store and variable operation of the CLI is a method on `EnvironmentStore`; the
[setup script](#set-up-the-example-stores) above already used `create_store()`, `set_many()`,
`set()` and `list_stores()`. The exceptions are `envs import`, `envs run` and
`envs export-shell`, which have no library method (see below for importing).

`set_many()` writes all variables in one go (one revision). If a variable already exists, the
call fails with `VariableExistsError` and writes nothing, unless you pass `overwrite=True`:

```python
es = EnvironmentStore("sqlite:///envs.db")
es.set_many("base", {"DB_HOST": "x", "LOG_LEVEL": "debug"})
# VariableExistsError: variables already exist in store 'base': DB_HOST, LOG_LEVEL; pass overwrite=True to replace them
es.set_many("base", {"LOG_LEVEL": "info", "FEATURE_X": "on"}, overwrite=True)  # fine
es.delete("base", ["FEATURE_X"])  # deletes several in one write
print(es.variables("base"))
```

```text
{'DB_HOST': 'localhost', 'DB_PORT': '5432', 'LOG_LEVEL': 'info'}
```

**Importing a file.** There is no `import` method: parse the file yourself and pass the result
to `set_many()`. For a JSON file with string values:

```python
import json

# local.json: {"API_URL": "http://localhost:8000", "DEBUG": "true"}
es.create_store("local")
es.set_many("local", json.loads(Path("local.json").read_text()))
print(es.variables("local"))
```

```text
{'API_URL': 'http://localhost:8000', 'DEBUG': 'true'}
```

For TOML use `tomllib.loads()`; for a `.env` file use `dotenv_values()` from python-dotenv (it
returns `None` for a name without `=`, so filter those out). Every value must be a string. Or
call `envs import -s local -f .env` from the command line.

Copying, moving, encrypting and re-keying:

```python
from environment_store import Passphrase

# A copy keeps the encryption (and key) of the source by default.
es.copy_store("base", "base-backup")

# encryption="plain" makes an unencrypted copy; this is the only way to decrypt.
es.copy_store("prod", "prod-plain", key=Path("prod.key"), encryption="plain")

# Any other KeyInput encrypts the copy with a different secret.
generate_key_file("staging.key")
es.copy_store("prod", "staging", key=Path("prod.key"), encryption=Path("staging.key"))

# Rename; a failure never leaves zero copies.
es.move_store("base-backup", "base-old")

# Copy into another backend: pass a second EnvironmentStore as `to`.
with EnvironmentStore("json://exported") as other:
    es.copy_store("base", "base", to=other)

# Encrypt a plaintext store (there is no way back in place).
es.encrypt_store("prod-plain", key=Path("staging.key"))

# Switch to a new secret; this can also switch between key file and passphrase.
es.rekey_store("prod-plain", old=Path("staging.key"), new=Passphrase(text="new passphrase"))

es.delete_store("base-old")  # needs no key, even for an encrypted store
```

For SQL backends, `es.migrate()` creates or upgrades the schema and returns a
`MigrationReport`, for example `MigrationReport(from_version=1, to_version=1, created=False)`.
SQLite does this automatically on open. PostgreSQL creates a missing schema automatically, but
an older schema is refused until someone runs `migrate()` (or `envs migrate`). On a JSON or TOML
backend `migrate()` raises `ValidationError`.

After `close()` (or the end of the `with` block), `es.closed` is `True` and every further call
raises `ValidationError: this EnvironmentStore is closed`. `close()` can be called twice.

## How do I work with encrypted stores?

Every method that reads or writes variables of an encrypted store takes `key=`. A key is a
`KeyInput`, which is one of three types:

| Type | Use it for |
|---|---|
| `Path("prod.key")` | A key file, or a passphrase file. The store decides how the file is read: a key file store expects `envstore-key-v1:...`; a passphrase store reads the file as text, with one trailing newline removed. |
| `Passphrase(text="...")` | A passphrase you already have in memory. |
| `KeyMaterial(key=b"...")` | A raw 32-byte key, or key text (`envstore-key-v1:...`, e.g. from a secret manager) parsed with `parse_key_text(text)`. |

A plain `str` is refused on purpose, because it could be a path or a passphrase:

```text
ValidationError: a key must be a Path, KeyMaterial or Passphrase, got str; a plain string is refused because it could be a path or a passphrase: use Path(...), Passphrase(text=...) or, for key text, parse_key_text(...)
```

Reading without a key, or with the wrong one:

```python
from environment_store import DecryptionError, KeyRequiredError, Source

with EnvironmentStore("sqlite:///envs.db") as es:
    try:
        es.variables("prod")
    except KeyRequiredError as exc:
        print(exc)
    print(es.variables("prod", key=Path("prod.key")))
    env = es.load(["base", Source("prod", key=Path("prod.key"))])
    print(env.variables())
```

```text
store 'prod' is encrypted (keyfile mode): a key or passphrase is required
{'DB_PASSWORD': 'hunter2'}
{'DB_HOST': 'localhost', 'DB_PORT': '5432', 'LOG_LEVEL': 'info', 'DB_PASSWORD': 'hunter2'}
```

A wrong key raises
`DecryptionError: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified`.
Passing a key for a plaintext store raises `NotEncryptedError`.

In `es.load()` you attach keys to stores with `Source(name, key=...)`; plain names are fine for
plaintext stores. With `environment_store.load()` you pass a dict instead:

```python
environment_store.load("base", "prod", keys={"prod": Path("prod.key")})
```

A key for a store that is not loaded is an error
(`ValidationError: a key was given for store 'prod', which is not loaded`).

Creating keys:

```python
from environment_store import generate_key_file, generate_key_text

generate_key_file("prod.key")  # mode 0600; never overwrites an existing file
text = generate_key_text()  # 'envstore-key-v1:...\n', e.g. for a password manager
```

Key text from a secret manager or an environment variable needs no key file: `parse_key_text()`
turns it into a `KeyMaterial` that works wherever a key does (`key=`, `Source(..., key=...)`,
`load(keys={...})`):

```python
import os

from environment_store import load, parse_key_text

load("prod", keys={"prod": parse_key_text(os.environ["PROD_STORE_KEY"])})
```

Text that is not key text raises `InvalidKeyFileError`; the message never contains the text.

The library never stores or caches keys, and `KeyMaterial`, `Passphrase` and `Source` hide them
in `repr()` (`Passphrase(<redacted>)`, `Source(name='prod')`).

**The key variable.** Without an explicit key, `EnvironmentStore` methods, `es.load()` and
`environment_store.load()` read an existing store's key or passphrase from the environment
variable `ENV_STORE_KEY_<STORE>`: the store name in upper case with `-` turned into `_`
(`ENV_STORE_KEY_PROD` for `prod`, `ENV_STORE_KEY_CUSTOMER_A` for `customer-a`). It holds the key
line (`envstore-key-v1:…`) or the passphrase, as a key file or passphrase file would. This is
meant for deployments that cannot ship a key file, such as Heroku config vars; see
[Deploying with encrypted stores](deployment.md). `ENV_STORE_LOAD` can hold the keys of several
stores at once, and counts as the same step; see
[How do I deploy with two environment variables?](#how-do-i-deploy-with-two-environment-variables).

| Key of an existing store, highest priority first | `EnvironmentStore` methods, `es.load()` | `environment_store.load()` |
|---|---|---|
| 1. explicit | `key=`, `Source(name, key=…)`, `rekey_store(old=…)` | `keys={"prod": …}` |
| 2. environment | `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD` | `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD` |
| 3. project file | — | `[keys]` in `.envstore.toml` |
| 4. prompt | — (`KeyRequiredError`) | hidden prompt, unless `noinput=True` or no terminal |

`keys=` or `key=` versus the variable: pass the key explicitly when your code already has it (a
file path, or text from a secret manager through `parse_key_text()`); rely on the variable when
the platform provides it. An explicit key always wins, so a `keys=` entry hides a wrong variable.

- An empty or invalid value raises a key error (`KeySourceError`, `InvalidKeyFileError`, or
  `KeyModeMismatchError` for key text in a passphrase store's variable), and a key that does not
  fit the store raises `DecryptionError`. Messages name the variable, never its
  value.
- The variable of a plaintext store, and of a store that is not used, is ignored. So is a key in
  `ENV_STORE_LOAD` for such a store.
- If both `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD` have a key for the same store, it is
  unclear which one is meant, so reading the store raises `ValidationError`, unless an explicit
  key is given:

  ```text
  ValidationError: store 'prod' gets a key from both ENV_STORE_KEY_PROD and ENV_STORE_LOAD, so it is unclear which one is meant: set only one of them
  ```

- A secret of the wrong kind in `ENV_STORE_LOAD` (key text for a passphrase store, or a
  passphrase for a key file store) raises `KeyModeMismatchError`.
- Two encrypted stores of one call that share a variable (`my-app` and `my_app`) raise
  `ValidationError` while it is set, unless an explicit key is given for both.
- New keys never come from it: `create_store(encrypt=True, key=…)`, `encrypt_store`, the `new=` of
  `rekey_store` and the `encryption=` of `copy_store` / `move_store` take only what you pass.
  `rekey_store(store, new=…)` without `old=` takes the old key from the variable or from
  `ENV_STORE_LOAD`.
- `EnvironmentStore` looks the variable up in `os.environ`, or in the mapping you pass as
  `environ=` (`EnvironmentStore(connection, environ={...})`, `from_env(environ=...)`);
  `es.environment_secret("prod")` returns the secret it finds there (in `ENV_STORE_KEY_PROD` or
  `ENV_STORE_LOAD`), or `None`, and `es.environment_key_source("prod")` names the variable it
  would come from (`'ENV_STORE_KEY_PROD'`, `'ENV_STORE_LOAD'` or `None`) without reading the
  store.
- The library never removes the variable from `os.environ`. If your process starts other
  programs, drop it after loading: `os.environ.pop("ENV_STORE_KEY_PROD", None)`, and the same for
  `ENV_STORE_LOAD`. (`envs run` removes `ENV_STORE_LOAD` and every `ENV_STORE_KEY_*` variable for
  you.)

**Prompting.** When `environment_store.load()` meets an encrypted store without a key, it asks
for it with a hidden prompt, but only if stdin is a terminal and `noinput` is `False`. Otherwise
it raises `KeyRequiredError`. `EnvironmentStore` methods never prompt.

## How do I use an encrypted store in CI?

In CI nothing can be typed, so give every key explicitly and pass `noinput=True`, so that a
missing key fails fast instead of waiting for input:

```python
environment_store.load(
    "base", "prod", keys={"prod": Path(os.environ["PROD_KEY_FILE"])}, noinput=True
)
```

Most CI systems can write a secret to a file and give you its path. If yours only offers the
secret as an environment variable, name it `ENV_STORE_KEY_PROD` and leave out `keys=`:

```python
environment_store.load("base", "prod", noinput=True)  # key from ENV_STORE_KEY_PROD
```

For a secret under another name, turn the text into a key with `parse_secret()`, which reads it
the way the store expects (key file text or passphrase):

```python
import os
from environment_store import EnvironmentStore, Source

with EnvironmentStore.from_env() as es:
    secret = es.parse_secret("prod", os.environ["PROD_KEY"])
    print(secret)
    env = es.load(["base", Source("prod", key=secret)])
print(sorted(env.apply()))
```

```text
KeyMaterial(<redacted>)
['DB_HOST', 'DB_PASSWORD', 'DB_PORT', 'LOG_LEVEL']
```

`env.apply()` returns the variables it actually set. A passphrase store works the same way, with
a passphrase file:

```python
environment_store.load("customer-a", keys={"customer-a": Path("customer-a.pass")}, noinput=True)
```

Without a key, CI fails with a clear error:

```text
KeyRequiredError: store 'prod' is encrypted and no key or passphrase was given; pass key=... (or keys={'prod': ...} to load()), or set ENV_STORE_KEY_PROD
```

## How do I deploy with two environment variables?

A deployment needs the connection, the stores to load and the key of every encrypted one. Two
environment variables carry all of it:

- `ENV_STORE_CONNECTION`: the connection string.
- `ENV_STORE_LOAD`: a **load specification**, one line that holds the stores in load order
  (repeats kept) and the key or passphrase of every encrypted one. Treat the value as opaque. It
  is as secret as all its keys together, so keep it in a secret manager, never in a file under
  version control.

Build the value where the keys are, with `EnvironmentStore.load_spec()`. It resolves keys like
`es.load()` (an explicit key, else the environment) and decrypts every store, so a wrong key
fails here and not in the deployment:

```python
from pathlib import Path
from environment_store import EnvironmentStore, Source

with EnvironmentStore("sqlite:///envs.db") as es:
    spec = es.load_spec(["base", Source("prod", key=Path("prod.key"))])
print(spec)
print(spec.encode())  # the value of ENV_STORE_LOAD
```

```text
LoadSpec(stores=('base', 'prod'), keys=mappingproxy({'prod': KeyMaterial(<redacted>)}))
envstore-load-v1:eyJzdG9yZXMiOlsiYmFzZSIsInByb2QiXSwia2V5cyI...
```

The `repr` hides the keys; `encode()` does not, and gives the same text for the same
specification. On the command line, `envs export-credentials base prod -k prod=prod.key` prints
both variables as dotenv lines, with a relative path in the connection string made absolute; see
[cli.md](cli.md).

Put both variables into the secret settings of your platform (CI, Kubernetes, Heroku). The
application then needs no project file, no key file and no store names:

```python
from environment_store import load

load(use_project=False, noinput=True)
```

With `ENV_STORE_LOAD` set, `load()` without store names loads its stores with its keys, and
`keys=` still beats it. Stores named in the call beat the stores of `ENV_STORE_LOAD`; its keys
for stores you do not load are ignored. An empty `ENV_STORE_LOAD` counts as unset.

An invalid value stops `load()` and every key lookup with `ConfigurationError`. The message says
why, never what the value holds:

```text
ConfigurationError: ENV_STORE_LOAD is not a valid load specification: the text after the prefix is not URL-safe base64 without padding
```

To read or write the value yourself, use `LoadSpec`: `LoadSpec(stores=("base", "prod"),
keys={"prod": secret})` takes a `KeyMaterial` or `Passphrase` per encrypted store, and
`LoadSpec.decode(text)` reads `encode()`'s text back; text that is not a load specification
raises `ConfigurationError: the text is not a valid load specification: ...`.

## Which errors should I catch?

Every error derives from `EnvironmentStoreError`, and every class is importable from
`environment_store`. Messages never contain values, keys or passphrases, so they are safe to log.

Messages speak Python: when there is a remedy, it names the library's own parameters and
functions, never a CLI flag. Every error has two attributes: `detail` says what went wrong, and
`hint` holds the remedy or `None`. The message is `detail`, followed by `; hint` when there is one.
The CLI and the TUI show the same `detail` with their own remedy in place of `hint`.

| Situation | Error | `hint` |
|---|---|---|
| encrypted store, no key | `KeyRequiredError` | `pass key=... (or keys={'prod': ...} to load()), or set ENV_STORE_KEY_PROD` |
| variables exist | `VariableExistsError` | `pass overwrite=True to replace them` |
| `to_file()` onto an existing file | `ValidationError` | `pass force=True to replace it` |
| `to_file()` cannot infer the format | `ValidationError` | `pass fmt='dotenv', fmt='json' or fmt='toml'` |
| a value dotenv cannot hold | `ValidationError` | `export with fmt='json' or fmt='toml', or set the variables with Environment.apply() instead` |
| not a valid key file or key text | `InvalidKeyFileError` | `create one with generate_key_file() or generate_key_text()` |

```python
from environment_store import VariableExistsError

try:
    es.set("base", "DB_HOST", "db.local")
except VariableExistsError as exc:
    print(exc.detail)
    print(exc.hint)
```

```text
variables already exist in store 'base': DB_HOST
pass overwrite=True to replace them
```

| Catch | When | CLI exit code |
|---|---|---|
| `ValidationError` (also a `ValueError`) | bad store or variable name, bad argument, a plain `str` as key, closed store, value refused by dotenv, a key in both `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD`. Subclasses: `AlreadyEncryptedError`, `NotEncryptedError`, `PlaintextNotAllowedError` | 1 |
| `ConfigurationError` | no connection, no stores, broken `.envstore.toml`, invalid `ENV_STORE_LOAD` | 1 |
| `MissingExtraError` | an optional dependency is missing; `.extra` names it (`"postgres"`) | 1 |
| `BackendError` | the database or files cannot be used. Subclasses: `UnsupportedFormatError`, `DatabaseNotCleanError`, `SchemaOutdatedError`, `SchemaTooNewError`, `SetupPrivilegeError` | 1 |
| `NotFoundError` | `StoreNotFoundError`, or `VariableNotFoundError` with `.names` and `.store` | 2 |
| `AlreadyExistsError` | `StoreExistsError`, or `VariableExistsError` with `.names` and `.store` | 3 |
| `CryptoError` | `KeyRequiredError`, `DecryptionError`, `InvalidKeyFileError`, `KeyModeMismatchError`, `KeySourceError` | 4 |
| `ConcurrentModificationError` | another process changed the store at the same time; nothing was written, try again | 5 |

For example:

```python
from environment_store import VariableNotFoundError

try:
    es.delete("base", ["NOPE", "ALSO_NOPE"])
except VariableNotFoundError as exc:
    print(exc)
    print(exc.names, exc.store)
```

```text
variables not found in store 'base': NOPE, ALSO_NOPE
('NOPE', 'ALSO_NOPE') base
```

`load()` also emits a `CredentialsInProjectFileWarning` (a `UserWarning`) when the
`connection` in `.envstore.toml` contains a password. Turn it into an error in your tests with
`warnings.simplefilter("error", CredentialsInProjectFileWarning)`.

## Typing notes

- The package ships `py.typed`, and every public function and method is fully annotated. Type
  checkers such as ty, mypy and pyright see the real signatures.
- `KeyInput` is the type alias `Path | KeyMaterial | Passphrase`, and `Secret` is
  `KeyMaterial | Passphrase`. Use them in your own signatures. A type checker flags a plain
  string as key, before the runtime check does:

  ```text
  error[invalid-argument-type]: Argument to bound method `EnvironmentStore.variables` is incorrect
    |     es.variables("prod", key="prod.key")
    |                          ^^^^^^^^^^^^^^ Expected `KeyInput | None`, found `Literal["prod.key"]`
  ```

- Values are always `str`; `variables()`, `nested_flat()` and `apply()` return `dict[str, str]`.
  `variables()` and `apply()` follow the merged order: stores in load order, each store's
  names sorted, a shared name at its first position (see
  [the order of the merged variables](#the-order-of-the-merged-variables)).
  `nested_flat()` and `apply(nested=True)` also keep the stores in load order and sort the
  variables within each store, so `PROD__A` can come before `BASE__Z`.
- `Source`, `KeyMaterial`, `Passphrase`, `LoadSpec`, `StoreInfo`, `MigrationReport` and
  `Environment` are frozen dataclasses. Their secret-holding arguments are keyword-only
  (`Source("prod", key=...)`, `Passphrase(text=...)`).
- `MergeOrder`, `KeyMode`, `Format` and `SetupMode` are `StrEnum`s, so `"json"` and `Format.JSON`
  are interchangeable where a format is taken.
- `StoreInfo.created_at` and `updated_at` are timezone-aware UTC datetimes.

## API reference

Everything below is importable from `environment_store`. Signatures are taken from the code.

### Functions

| Signature | Description |
|---|---|
| `load(*stores: str, connection: str \| None = None, keys: Mapping[str, KeyInput] \| None = None, first_wins: bool = False, overwrite: bool = False, nested: bool = False, use_project: bool = True, noinput: bool = False) -> Environment` | Resolve settings like the CLI, load the stores and apply them to `os.environ`. |
| `generate_key_file(path: Path \| str \| os.PathLike[str]) -> None` | Write a new key file with mode `0600`; an existing path raises `ValidationError`. |
| `generate_key_text() -> str` | Return a new key as `'envstore-key-v1:...\n'`. |
| `parse_key_text(text: str) -> KeyMaterial` | Parse key text (`envstore-key-v1:...`, surrounding whitespace ignored) into a key without a file; invalid text raises `InvalidKeyFileError`. |

### `EnvironmentStore`

`EnvironmentStore(connection: str, *, setup: SetupMode = SetupMode.AUTO, clock=..., kdf_params_factory=None, opener=..., environ: Mapping[str, str] | None = None)`

Opens the backend immediately. Use it as a context manager or call `close()`. `clock`,
`kdf_params_factory` and `opener` exist for testing; leave them at their defaults.
`setup=SetupMode.NONE` skips the database check on open; the first data operation then does it.
`environ` is where `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD` are looked up; `None` means
`os.environ`.

| Method | Description |
|---|---|
| `from_env(*, environ: Mapping[str, str] \| None = None, setup=SetupMode.AUTO, ...) -> Self` (classmethod) | Open the backend in `ENV_STORE_CONNECTION` (from `environ`, default `os.environ`, which is also where `ENV_STORE_KEY_<STORE>` and `ENV_STORE_LOAD` are looked up). |
| `from_settings(settings, *, setup=SetupMode.AUTO, ..., environ=None) -> Self` (classmethod) | Open from resolved settings; used internally by `load()` and the CLI. |
| `close() -> None` | Close the backend; safe to call twice. |
| `closed` (property) `-> bool` | Whether `close()` was called. |
| `list_stores() -> list[StoreInfo]` | All stores, sorted by name; needs no key. |
| `store_info(name: str) -> StoreInfo` | One store's listing entry; needs no key. |
| `create_store(name: str, *, encrypt: bool = False, key: KeyInput \| None = None) -> StoreInfo` | Create an empty store; `encrypt=True` needs `key`. |
| `delete_store(name: str) -> None` | Delete a store; needs no key. |
| `copy_store(src: str, dst: str, *, key: KeyInput \| None = None, encryption: Literal['same', 'plain'] \| KeyInput = 'same', to: EnvironmentStore \| None = None) -> StoreInfo` | Copy a store under a new name or into another backend. |
| `move_store(src: str, dst: str, *, key: KeyInput \| None = None, encryption: Literal['same', 'plain'] \| KeyInput = 'same', to: EnvironmentStore \| None = None) -> StoreInfo` | Copy, then delete the source; never leaves zero copies. |
| `variables(store: str, *, key: KeyInput \| None = None) -> dict[str, str]` | All variables of a store. |
| `get(store: str, name: str, *, key: KeyInput \| None = None) -> str` | One value. |
| `set(store: str, name: str, value: str, *, key: KeyInput \| None = None, overwrite: bool = False) -> None` | Set one variable. |
| `set_many(store: str, values: Mapping[str, str], *, key: KeyInput \| None = None, overwrite: bool = False) -> None` | Set several variables in one write. |
| `delete(store: str, names: Collection[str], *, key: KeyInput \| None = None) -> None` | Delete variables in one write. |
| `encrypt_store(store: str, *, key: KeyInput) -> None` | Encrypt a plaintext store; there is no way back. |
| `rekey_store(store: str, *, old: KeyInput \| None = None, new: KeyInput) -> None` | Re-encrypt with a new secret; `old=None` takes the old key from `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD`. |
| `secret_for(store: str, key: KeyInput) -> Secret` | Turn a key input into the store's secret (reads a `Path`). |
| `environment_secret(store: str) -> Secret \| None` | The store's secret from `ENV_STORE_KEY_<STORE>` or `ENV_STORE_LOAD`, or `None` if neither has a key for the store or the store is plaintext; a key in both raises `ValidationError`. |
| `environment_key_source(store: str) -> str \| None` | `'ENV_STORE_KEY_<STORE>'` when that variable is set, else `'ENV_STORE_LOAD'` when it has a key for the store, else `None`; does not read the store. |
| `parse_secret(store: str, text: str) -> Secret` | Interpret key file text or a passphrase by the store's key mode. |
| `load(sources: Sequence[Source \| str], *, order: MergeOrder = MergeOrder.LAST_WINS) -> Environment` | Read stores for merging; does not touch `os.environ`. |
| `load_spec(sources: Sequence[Source \| str]) -> LoadSpec` | Resolve keys like `load()`, decrypt every store and return the [load specification](#how-do-i-deploy-with-two-environment-variables) for `ENV_STORE_LOAD`. |
| `migrate() -> MigrationReport` | Create or upgrade a SQL schema. |

### `Environment`

`Environment(*, stores: tuple[tuple[str, Mapping[str, str]], ...], order: MergeOrder)`; you get
one from `load()` or `EnvironmentStore.load()`. Its `repr` hides the values.

| Method | Description |
|---|---|
| `variables() -> dict[str, str]` | The merged variables, in [merged order](#the-order-of-the-merged-variables). |
| `with_sources() -> dict[str, tuple[str, str]]` | `{name: (value, store)}`, naming the winning store; same order as `variables()`. |
| `nested() -> dict[str, dict[str, str]]` | `{store: {name: value}}` in load order; a store listed twice raises `ValidationError`. |
| `nested_flat() -> dict[str, str]` | `{"STORE__NAME": value}`; a name collision raises `ValidationError`. |
| `apply(*, overwrite: bool = False, nested: bool = False, environ: MutableMapping[str, str] \| None = None) -> dict[str, str]` | Write into `os.environ` (or `environ`); returns what was set. |
| `dumps(fmt: Format \| str, *, nested: bool = False) -> str` | Serialize as dotenv, JSON or TOML. |
| `to_file(path: Path \| str \| os.PathLike[str], *, fmt: Format \| str \| None = None, nested: bool = False, force: bool = False) -> None` | Write a file with mode `0600`; `fmt=None` infers it from the name. |

### Value types and enums

| Name | Definition |
|---|---|
| `Source(name: str, *, key: KeyInput \| None = None)` | One store in a load list, with its key. |
| `KeyMaterial(*, key: bytes)` | A raw key; exactly 32 bytes. |
| `Passphrase(*, text: str)` | A passphrase; must not be empty. |
| `KeyInput` | `Path \| KeyMaterial \| Passphrase` |
| `Secret` | `KeyMaterial \| Passphrase` |
| `LoadSpec(*, stores: tuple[str, ...], keys: Mapping[str, Secret] = {})` | The stores to load, in order, and the secret of every encrypted one; at least one store, keys only for stores it loads. `encode() -> str` gives the value of `ENV_STORE_LOAD`; `LoadSpec.decode(text: str) -> LoadSpec` (classmethod) reads it back and raises `ConfigurationError` for other text. Its `repr` hides the keys. |
| `StoreInfo(*, name: str, encrypted: bool, key_mode: KeyMode \| None, revision: int, created_at: datetime, updated_at: datetime)` | A store listing entry. |
| `MigrationReport(*, from_version: int \| None, to_version: int, created: bool)` | What `migrate()` did. |
| `MergeOrder` | `LAST_WINS = "last_wins"`, `FIRST_WINS = "first_wins"` |
| `KeyMode` | `KEYFILE = "keyfile"`, `PASSPHRASE = "passphrase"` |
| `Format` | `DOTENV = "dotenv"`, `JSON = "json"`, `TOML = "toml"` |
| `SetupMode` | `AUTO = "auto"`, `NONE = "none"` |
| `CredentialsInProjectFileWarning` | `UserWarning` subclass emitted by `load()` |
| `__version__` | The package version, e.g. `'2.0.0'` |

The error classes are listed in [Which errors should I catch?](#which-errors-should-i-catch).
