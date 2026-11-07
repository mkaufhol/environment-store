<p align="center">
  <img src="https://raw.githubusercontent.com/mkaufhol/environment-store/main/docs/assets/environment-store-logo.svg" alt="Environment Store logo" width="200">
</p>

<h1 align="center">Environment Store</h1>

Environment Store keeps your environment variables in **named stores**: flat collections of `NAME=value`
pairs such as `base`, `dev`, `prod` or `customer-a`. Stores live in a backend you pick with a connection string:
JSON or TOML files in a directory, a SQLite file, or a PostgreSQL database. Any store can be encrypted as a whole
with AES-256-GCM, using a key file or a passphrase. You use the stores from the `envs` command line tool, from
Python with one function call, or from a terminal UI. An
[agent skill](https://github.com/mkaufhol/environment-store/blob/feature/v2/.claude/skills/environment-store-cli/SKILL.md)
teaches coding agents how to drive the CLI safely.

> **Version 2.0 is in development (`2.0.0.dev0`) and not on PyPI yet.** `environment-store` on PyPI is currently
> the old 0.1 line, which has no `envs` command. Until 2.0 is released, install it from the Git repository as
> shown below;
> [Installation](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/installation.md) has the details.

## Install

The docs use [uv](https://docs.astral.sh/uv/): `uv tool install` gives `envs` its own isolated environment and
puts only the command on your `PATH`, `uvx` runs it once without installing, and `uv add` adds the library to a
project. pip works too. Python 3.13 or newer is needed.

| Extra | Adds | Install with uv (once 2.0 is on PyPI) | pip |
|---|---|---|---|
| *(core)* | Python library, encryption, JSON/TOML/SQLite backends | `uv add environment-store` | `pip install environment-store` |
| `cli` | the `envs` command | `uv tool install 'environment-store[cli]'` | `pip install 'environment-store[cli]'` |
| `postgres` | the `postgresql://` backend (psycopg) | `uv tool install 'environment-store[cli,postgres]'` (CLI) or `uv add 'environment-store[postgres]'` (library) | `pip install 'environment-store[cli,postgres]'` (CLI) or `pip install 'environment-store[postgres]'` (library) |
| `tui` | `envs tui` (with `cli`) | `uv tool install 'environment-store[cli,tui]'` | `pip install 'environment-store[cli,tui]'` |
| `all` | all of the above | `uv tool install 'environment-store[all]'` | `pip install 'environment-store[all]'` |

Combine extras with commas, as in `[cli,postgres]`. A missing extra makes `envs` exit with a message that names
it. Until 2.0 is on PyPI, add the repository URL to the same command:

```console
$ uv tool install 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2'
$ envs --version
environment-store 2.0.0.dev0
```

To try it without installing:
`uvx --from 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2' envs -h`.
`envs -h` (or `--help`) works on every command; the repository also has a
[man page](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/man/share/man/man1/envs.1) and a
[tldr page](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/tldr/envs.md).

## The CLI in 30 seconds

After installing, in any directory:

```console
$ export ENV_STORE_CONNECTION=json://.envs        # keep the stores as JSON files in ./.envs

$ envs create-store base
created store 'base'
$ envs set -s base DB_HOST=localhost DB_PORT=5432 LOG_LEVEL=info
set DB_HOST, DB_PORT, LOG_LEVEL in store 'base'
$ envs create-store dev
created store 'dev'
$ envs set -s dev DB_HOST=dev.example.com DEBUG=true
set DB_HOST, DEBUG in store 'dev'

$ envs ls -v --source base dev                    # later stores win; base's names first (sorted)
DB_HOST=dev.example.com  dev
DB_PORT=5432             base
LOG_LEVEL=info           base
DEBUG=true               dev

$ envs run base dev -- sh -c 'echo "$DB_HOST:$DB_PORT debug=$DEBUG"'
dev.example.com:5432 debug=true

$ envs export base dev -f .env
exported to '.env'
```

## Python in 5 lines

```python
import os
import environment_store

environment_store.load("base", "dev", connection="json://.envs")
print(os.environ["DB_HOST"])  # dev.example.com
```

`load()` works like `load_dotenv()`: it merges the stores and puts the variables into `os.environ`. Variables that
are already set are kept unless you pass `overwrite=True`.

## Features

- **Named, layered stores.** Combine `base` + `dev` + `customer-a` in one call; the last store wins, or the first
  with `--first-wins`. The output lists the stores in load order, each store's names sorted by name, and
  `--source` shows which store each value comes from.
- **Four backends, one interface.** `json://dir`, `toml://dir`, `sqlite:///file.db`, `postgresql://host/db`. Move
  or copy a store between backends with `envs mv-store` / `envs cp-store --to`.
- **Optional encryption per store.** AES-256-GCM with a random key file or an Argon2id passphrase. Names and
  values are encrypted together. Keys are never stored, cached or accepted as literal command line text.
- **Load anywhere.** `envs run` starts a command with the variables, `eval "$(envs export-shell ...)"` loads them
  into a POSIX shell, `envs export` writes dotenv, JSON or TOML, and `environment_store.load()` fills `os.environ`.
- **Safe dotenv files.** Exported `.env` files read back exactly with both python-dotenv and Docker Compose; values
  that cannot be written safely are refused with a clear hint instead of being written wrong.
- **Project file.** A `.envstore.toml` in your project names the connection, the default stores and the key files,
  so `envs run -- ./manage.py runserver` is all you type.
- **Scriptable.** Data on stdout, messages on stderr, `--json` output, stable exit codes and `--noinput` for CI.
- **Terminal UI.** `envs tui` lets you browse stores and add, edit and delete variables, with values masked and
  each screen's keys in its footer.

## Documentation

| Guide | What it covers |
|---|---|
| [Quickstart](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/quickstart.md) | From install to plain and encrypted stores, `.env` export, `envs run` and Python, in ten minutes |
| [Installation](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/installation.md) | uv (`uv tool install`, `uvx`, `uv add`) and pip, installing from the repository today, every optional extra, man and tldr pages |
| [CLI reference](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/cli.md) | Every command and option, with examples |
| [Python library](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/python.md) | `load()`, `EnvironmentStore`, `Environment`, keys and errors |
| [Configuration](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/configuration.md) | Connection strings, `.envstore.toml`, environment variables, merge order |
| [Encryption and keys](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/encryption.md) | Key files, passphrases, `rekey`, `encrypt`, decrypting with `cp-store --plain` |
| [Terminal UI](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/tui.md) | `envs tui` screens and key bindings |
| [Agent skill](https://github.com/mkaufhol/environment-store/blob/feature/v2/.claude/skills/environment-store-cli/SKILL.md) | Instructions for coding agents that use the `envs` CLI |

The links in this README are absolute so that they also work on PyPI. Until 2.0 is merged into `main` they point
at the `feature/v2` branch, where the 2.0 documentation lives. The
[documentation index](https://github.com/mkaufhol/environment-store/blob/feature/v2/docs/README.md) lists the guides by task.

## Contributing

- What 2.0 does: [SPEC-V2.md](https://github.com/mkaufhol/environment-store/blob/feature/v2/SPEC-V2.md)
- How it is built: [IMPLEMENTATION-PLAN.md](https://github.com/mkaufhol/environment-store/blob/feature/v2/IMPLEMENTATION-PLAN.md)
- How to contribute (binding rules: TDD, typing, 100 % coverage):
  [CONTRIBUTING.md](https://github.com/mkaufhol/environment-store/blob/feature/v2/CONTRIBUTING.md)

## License

MIT, see [LICENSE](https://github.com/mkaufhol/environment-store/blob/feature/v2/LICENSE).
