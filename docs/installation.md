# Installation

Environment Store is a Python package named `environment-store`. It needs **Python 3.13 or newer** and runs on
Linux, macOS and Windows (the CLI's `run` command and the project file trust check behave slightly differently on
Windows; see the [CLI reference](cli.md)).

> **2.0 is not on PyPI yet.** PyPI has only the old 0.1 line (`0.1.0rc1`, `0.1.0rc2`), which has no `envs`
> command and no `cli` extra. pip and uv fall back to those pre-releases when nothing else exists, so
> `pip install 'environment-store[cli]'` installs 0.1 today, not 2.0. Until 2.0 is published,
> [install from source](#install-from-source-the-only-way-today). Whatever route you take, check with
> `envs --version`: it must print `environment-store 2.0.0.dev0` or later.

## Install from source (the only way today)

Clone the repository, switch to the 2.0 branch and install it into a virtual environment:

```console
$ git clone https://github.com/mkaufhol/environment-store.git
$ cd environment-store
$ git switch feature/v2
$ python3.13 -m venv .venv
$ . .venv/bin/activate
$ pip install -e '.[cli]'
$ envs --version
environment-store 2.0.0.dev0
```

Use `'.[all]'` instead of `'.[cli]'` for PostgreSQL support and the TUI as well (the extras are explained
[below](#optional-extras)). `-e` installs the checkout in editable mode, so a `git pull` updates the tool without
reinstalling.

To use the library in another project's virtual environment, install the clone by path from there:

```console
$ pip install -e '/path/to/environment-store[cli]'
```

## Which install do I need?

The table names the extras. Today you append them to the source install (`pip install -e '.[cli,postgres]'`);
once 2.0 is on PyPI the same extras work with the package name, as shown.

| You want… | Install (once 2.0 is on PyPI) |
|---|---|
| the `envs` command | `pip install 'environment-store[cli]'` |
| the command plus PostgreSQL | `pip install 'environment-store[cli,postgres]'` |
| everything: CLI, PostgreSQL, TUI | `pip install 'environment-store[all]'` |
| only the Python library in your app | `pip install environment-store` |
| the library with PostgreSQL in your app | `pip install 'environment-store[postgres]'` |

The quotes around `environment-store[...]` and `'.[...]'` matter in zsh, which would otherwise treat the brackets as
a pattern.

## Optional extras

The core package depends only on `cryptography`. It already contains the Python library, encryption, the JSON and
TOML file backends and SQLite (from the standard library). Everything else is an extra:

| Extra | Adds | Pulls in |
|---|---|---|
| *(none)* | Python library, encryption, `json://`, `toml://`, `sqlite:///` | `cryptography>=44` |
| `cli` | the `envs` / `environment-store` command | `typer>=0.26` |
| `postgres` | the `postgresql://` backend | `psycopg[binary]>=3.2` |
| `tui` | `envs tui`, the terminal UI (also needs `cli`) | `textual>=8.2` |
| `all` | all of the above | `typer`, `psycopg[binary]`, `textual` |

If you use a feature whose extra is missing, you get a clear message and exit code 1 instead of an import error.
For example, with only the core package installed:

```console
$ envs --version
Error: this feature needs the optional 'cli' dependencies: pip install 'environment-store[cli]'
```

The same message appears for `envs tui` without `tui`, and for a `postgresql://` connection without `postgres`.
In Python the latter raises `MissingExtraError`, whose `extra` attribute names the missing extra (`'postgres'`).

## Once 2.0 is on PyPI

These commands are for after the 2.0 release. Run them today and you get 0.1 (see the note at the top), so check
`envs --version` afterwards.

With pip, in a virtual environment:

```console
$ python3.13 -m venv .venv
$ . .venv/bin/activate
$ pip install 'environment-store[cli]'
$ envs --version
```

With uv, in a uv-managed project:

```console
$ uv add 'environment-store[postgres]'        # library for your app
$ uv add --dev 'environment-store[cli]'       # the envs command for development
```

Installed once for your user, independent of any project: `uv tool install 'environment-store[all]'` or
`pipx install 'environment-store[cli]'`.

Run without installing: `uvx` runs the command in a temporary environment. Because the command is called `envs` but
the package is `environment-store`, name the package with `--from`:

```console
$ uvx --from 'environment-store[cli]' envs --version
```

If 2.0 is first published as a pre-release (for example `2.0.0rc1`), pin it so pip cannot pick 0.1:
`pip install 'environment-store[cli]>=2.0.0rc1'`.

## Entry points

The package installs two console commands that are exactly the same program:

| Command | Notes |
|---|---|
| `envs` | short name, used throughout these docs |
| `environment-store` | long name, for scripts where `envs` could be ambiguous |
| `python -m environment_store.cli` | the same CLI without a console script on `PATH` |

```console
$ python -m environment_store.cli --version
environment-store 2.0.0.dev0
```

There is no built-in shell completion.

## Check the installation

```console
$ envs --help
Usage: envs [OPTIONS] COMMAND [ARGS]...

  Keep environment variables in named, optionally encrypted stores and load
  them anywhere.
...
$ python -c 'import environment_store; print(environment_store.__version__)'
2.0.0.dev0
```

Next: the [Quickstart](quickstart.md).
