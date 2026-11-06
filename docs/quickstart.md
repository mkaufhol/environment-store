# Quickstart

This guide takes you from nothing to a working setup in about ten minutes. You will create a plain store and an
encrypted store, set and read variables, write a `.env` file, start a command with the variables and load them in
Python. Every command below was run against the real CLI, and the output shown is what it printed.

You need Python 3.13 or newer and a POSIX shell (bash, zsh). Work in an empty directory so you can delete
everything afterwards.

## 1. Install

Version 2.0 is not on PyPI yet (`pip install environment-store` currently gives you the old 0.1 line, which has no
`envs` command), so install it from a clone of the repository. Do this outside your empty work directory:

```console
$ git clone https://github.com/mkaufhol/environment-store.git && cd environment-store
$ git switch feature/v2
$ python3.13 -m venv .venv && . .venv/bin/activate
$ pip install -e '.[cli]'
$ envs --version
environment-store 2.0.0.dev0
```

Keep the virtual environment active and change into your empty work directory for the rest of the guide.

The `[cli]` extra adds the `envs` command. It is also installed as `environment-store`; both names run the same
tool. See [Installation](installation.md) for PostgreSQL support, the TUI and how to install once 2.0 is on PyPI.

## 2. Create a plain store

Every command that reads or writes stores needs to know **where** they live. That is the connection string. For
this guide, use a SQLite file in the current directory and put it in an environment variable so you do not have to
repeat it:

```console
$ export ENV_STORE_CONNECTION=sqlite:///envs.db
```

You could also pass it to each command with `-c`, for example `envs -c sqlite:///envs.db ls-store`, or save it in
a project file (step 9). Other backends are `json://dir`, `toml://dir` and `postgresql://...`; see
[Configuration](configuration.md).

Now create a store called `dev`:

```console
$ envs create-store dev
created store 'dev'
```

The SQLite file and its tables are created automatically. Store names use lowercase letters, digits, `_` and `-`,
and start with a letter: `dev`, `prod`, `customer-a`.

## 3. Set and get variables

`envs set` writes one or more variables into the store you name with `-s`, all in a single write:

```console
$ envs set -s dev DB_HOST=localhost DB_PORT=5432 DEBUG=true
set DB_HOST, DB_PORT, DEBUG in store 'dev'
```

List the variables. Without `-v` you see only the names; with `-v` you also see the values:

```console
$ envs ls -v dev
DB_HOST=localhost
DB_PORT=5432
DEBUG=true
```

Read a single value with `envs get NAME STORE`:

```console
$ envs get DB_HOST dev
localhost
```

When the output goes to a pipe or `$(...)`, `get` prints the raw value without a trailing newline, so
`host=$(envs get DB_HOST dev)` gives exactly `localhost`.

Setting a variable that already exists is refused (exit code 3), so you do not overwrite something by accident:

```console
$ envs set -s dev DEBUG=false
Error: variables already exist in store 'dev': DEBUG; use overwrite (-o/--overwrite) to replace them
```

Add `-o` to replace it: `envs set -s dev -o DEBUG=false`. This guide keeps `DEBUG=true`.

## 4. Create an encrypted store

Secrets go into an encrypted store. The simplest way is a key file: `--generate-key` creates a random key, writes
it to a file with permissions `0600` and encrypts the new store with it.

```console
$ envs create-store prod -e --generate-key prod.key
created store 'prod'
```

Keep `prod.key` safe and out of version control: without it the store cannot be read. (You can use a passphrase
instead of a key file; see [Encryption and keys](encryption.md).)

Encrypted stores do not accept `NAME=value` on the command line, because command lines end up in your shell
history:

```console
$ envs set -s prod DB_HOST=db.example.com -k prod.key
Error: store 'prod' is encrypted: values on the command line end up in the shell history; give one name and pipe its value on stdin (envs set -s prod NAME < FILE) or type it at the hidden prompt (envs set -s prod NAME)
```

Instead, give only the name. `-k` names the key file. In a terminal, `envs set` then asks for the value twice,
without showing what you type:

```console
$ envs set -s prod DB_PASSWORD -k prod.key
Value of DB_PASSWORD:
Repeat to confirm:
set DB_PASSWORD in store 'prod'
```

Type `s3cr3t-pa55` at both prompts to follow along. In scripts, pass the value on stdin from a file instead, for
example one your secret manager wrote. One trailing newline is removed from the value. The host name is not
secret, so `echo` is fine for creating the file here:

```console
$ echo db.example.com > db-host.txt
$ envs set -s prod DB_HOST -k prod.key < db-host.txt
set DB_HOST in store 'prod'
```

> **Do not type real secrets into a command line.** `printf 's3cr3t' | envs set ...` works, but it puts the secret in
> your shell history just like `NAME=value` would. Use the hidden prompt or `< FILE` for real secrets.

`ls-store` shows all stores and needs no key:

```console
$ envs ls-store
name  encryption
dev   plain
prod  encrypted (keyfile)
```

Reading an encrypted store without its key fails with exit code 4. On a terminal, the CLI would ask for the key
instead.

```console
$ envs get DB_PASSWORD prod
Error: store 'prod' is encrypted and no key or passphrase was given: pass it with -k <path> (or -k - for stdin)
$ envs get DB_PASSWORD prod -k prod.key
s3cr3t-pa55
```

## 5. Combine stores

Reading commands (`ls`, `get`, `export`, `export-shell`, `run`) take several stores. They are merged in the order
you give them, and **the last store wins** when two stores define the same variable. With several stores, bind
each key to its store with `-k STORE=PATH`. `--source` shows where each value comes from:

```console
$ envs ls -v --source dev prod -k prod=prod.key
DB_HOST=db.example.com   prod
DB_PASSWORD=s3cr3t-pa55  prod
DB_PORT=5432             dev
DEBUG=true               dev
```

`DB_HOST` comes from `prod` because `prod` is listed last. Add `--first-wins` to let the first store win instead.

Note that `ls -v` and `get` print decrypted secrets in plain text. Do not run them where the output is recorded,
such as CI logs or a shared screen.

## 6. Export a .env file

`envs export` writes the merged variables as dotenv (the default), JSON or TOML. Without `-f` it prints to stdout;
with `-f` it writes a new file with permissions `0600`:

```console
$ envs export dev -f .env
exported to '.env'
$ cat .env
DB_HOST=localhost
DB_PORT=5432
DEBUG=true
```

An existing file is never replaced unless you add `--force`. The file is **not encrypted**: exporting an encrypted
store writes its secrets to disk in plain text, so keep such files out of version control and delete them when you
no longer need them. The format follows the file name (`.env`, `.json`,
`.toml`), or set it with `-t json`. The dotenv output reads back exactly with python-dotenv and Docker Compose.

## 7. Run a command with the variables

`envs run` starts a command with the store variables added to its environment. Everything after `--` is the
command; no shell is involved unless you start one yourself:

```console
$ envs run dev -- sh -c 'echo "connecting to $DB_HOST:$DB_PORT"'
connecting to localhost:5432
$ envs run dev prod -k prod=prod.key -- sh -c 'echo "connecting to $DB_HOST:$DB_PORT"'
connecting to db.example.com:5432
```

Variables that are already set in your shell win over the stores; add `-o` to let the stores overwrite them. The
exit code of `envs run` is the exit code of the command, so it works in scripts and CI.

To load the variables into your current shell instead, use `export-shell`:

```console
$ eval "$(envs export-shell dev)"
$ echo "$DB_HOST $DEBUG"
localhost true
```

These variables now stay set in your shell. Because variables that are already set win over the stores, they
would hide the `prod` values in the next steps, so remove them again before you go on:

```console
$ unset DB_HOST DB_PORT DEBUG
```

## 8. Use the variables in Python

Install the library (the CLI extra already includes it) and call `load()` at the start of your program. It merges
the stores like the CLI and puts the variables into `os.environ`. Keys are given as `Path` objects:

```python
# app.py
import os
from pathlib import Path

import environment_store

environment_store.load(
    "dev", "prod", connection="sqlite:///envs.db", keys={"prod": Path("prod.key")}
)
print(os.environ["DB_HOST"], os.environ["DB_PASSWORD"])
```

```console
$ python app.py
db.example.com s3cr3t-pa55
```

Like the CLI, `load()` keeps variables that are already set unless you pass `overwrite=True`, and it reads
`ENV_STORE_CONNECTION` when you leave out `connection=`. For full control, open the backend yourself:

```python
from pathlib import Path
from environment_store import EnvironmentStore, Source

with EnvironmentStore("sqlite:///envs.db") as es:
    env = es.load(["dev", Source("prod", key=Path("prod.key"))])
    print(env.variables())
    # {'DB_HOST': 'db.example.com', 'DB_PASSWORD': 's3cr3t-pa55', 'DB_PORT': '5432', 'DEBUG': 'true'}
```

See [Python library](python.md) for the whole API.

## 9. Save your settings in a project file

Typing the connection, the store list and `-k` every time gets old. Put them in `.envstore.toml` at the root of your
project:

```toml
connection = "sqlite:///envs.db"
stores = ["dev", "prod"]

[keys]
prod = "prod.key"
```

Relative paths are resolved from the directory of the project file, so it works from any subdirectory. Now the
commands get much shorter:

```console
$ unset ENV_STORE_CONNECTION
$ envs ls -v --source
DB_HOST=db.example.com   prod
DB_PASSWORD=s3cr3t-pa55  prod
DB_PORT=5432             dev
DEBUG=true               dev
$ mkdir -p src/app && cd src/app
$ envs get DB_HOST
db.example.com
$ envs run -- sh -c 'echo $DB_PASSWORD'
s3cr3t-pa55
```

Python picks up the same file, so `environment_store.load()` with no arguments loads `dev` and `prod`.

Commit `.envstore.toml` if you like, but never commit the key files or the `.env` you exported. Do not put a
database password in `connection`; use `ENV_STORE_CONNECTION` for that. Details are in
[Configuration](configuration.md).

## 10. Clean up and next steps

Everything you created lives in this directory: `envs.db`, `prod.key`, `db-host.txt`, `.env`, `.envstore.toml`,
`app.py` and the empty `src/app` directory.
Delete the directory when you are done.

Where to go next:

- [CLI reference](cli.md): every command, `--json` output, exit codes
- [Encryption and keys](encryption.md): passphrases, `rekey`, `encrypt`, decrypting a copy
- [Configuration](configuration.md): backends, PostgreSQL, project file rules, CI with `--noinput`
- [Python library](python.md): `EnvironmentStore`, `Environment`, errors
- [Terminal UI](tui.md): `envs tui`
