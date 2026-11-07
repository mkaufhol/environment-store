# Installation

Environment Store is a Python package named `environment-store`. It needs **Python 3.13 or newer** and runs on
Linux, macOS and Windows (the CLI's `run` command and the project file trust check behave slightly differently on
Windows; see the [CLI reference](cli.md)).

These docs use [uv](https://docs.astral.sh/uv/) and show pip as the alternative. The reasons are practical:

- `uv tool install` gives the `envs` command its own isolated environment and links only the command onto your
  `PATH`. Its dependencies never clash with your projects, and you need no global `pip install`.
- `uvx` runs the command once in a throwaway environment, without installing anything.
- `uv add` records the library in your project's `pyproject.toml` and lock file, and `uv run` runs code and
  commands in that project's environment.

> **2.0 is not on PyPI yet.** PyPI has only the old 0.1 line (`0.1.0rc1`, `0.1.0rc2`), which has no `envs`
> command and no `cli` extra. uv and pip fall back to those pre-releases when nothing else exists, so
> `uv tool install 'environment-store[cli]'` installs 0.1 today, not 2.0. Until 2.0 is published,
> [install from the repository](#install-from-the-repository-the-only-way-today). Whatever route you take, check
> with `envs --version`: it must print `environment-store 2.0.0.dev0` or later.

## Which install do I need?

| You want… | With uv | With pip (in a virtual environment) |
|---|---|---|
| the `envs` command | `uv tool install 'environment-store[cli]'` | `pip install 'environment-store[cli]'` |
| the command plus PostgreSQL | `uv tool install 'environment-store[cli,postgres]'` | `pip install 'environment-store[cli,postgres]'` |
| everything: CLI, PostgreSQL, TUI | `uv tool install 'environment-store[all]'` | `pip install 'environment-store[all]'` |
| to run `envs` once, without installing | `uvx --from 'environment-store[cli]' envs --version` | |
| only the Python library in your app | `uv add environment-store` | `pip install environment-store` |
| the library with PostgreSQL in your app | `uv add 'environment-store[postgres]'` | `pip install 'environment-store[postgres]'` |
| the command inside a uv project | `uv add --dev 'environment-store[cli]'`, then `uv run envs ...` | |

These commands are for after the 2.0 release. Today, put the repository URL behind the same extras, as shown in
the next section. The quotes around `environment-store[...]` matter in zsh, which would otherwise treat the
brackets as a pattern.

`uvx` needs `--from` because the command is called `envs` but the package is `environment-store`.

## Install from the repository (the only way today)

uv installs straight from the Git repository. Write the extras after the package name and the branch after the
URL:

```console
$ uv tool install 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2'
$ envs --version
environment-store 2.0.0.dev0
```

More extras work the same way, for example `'environment-store[cli,postgres] @ git+https://...@feature/v2'`. The
same URL works for a one-off run and for the library:

```console
$ uvx --from 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2' envs --version
environment-store 2.0.0.dev0
$ uv add 'environment-store[postgres] @ git+https://github.com/mkaufhol/environment-store@feature/v2'
```

`uv add` writes `environment-store[postgres]` to your dependencies and the Git source to `[tool.uv.sources]`, so
switching to the PyPI release later means deleting that source. `uv tool upgrade environment-store` fetches the
latest commit of the branch. If `envs` is not found after `uv tool install`, uv's tool directory (usually
`~/.local/bin`) is not on your `PATH`; `uv tool update-shell` adds it.

With pip, the same URL works inside a virtual environment:

```console
$ python3.13 -m venv .venv
$ . .venv/bin/activate
$ pip install 'environment-store[cli] @ git+https://github.com/mkaufhol/environment-store@feature/v2'
```

### From a clone

To work on the code, or to follow the branch with `git pull`, clone the repository:

```console
$ git clone https://github.com/mkaufhol/environment-store.git
$ cd environment-store
$ git switch feature/v2
$ uv run --extra cli envs --version
environment-store 2.0.0.dev0
```

`uv run` creates the project's `.venv` on first use and runs the command in it. To get `envs` on your `PATH`
everywhere instead, install the clone as an editable tool, so a `git pull` updates it without reinstalling:

```console
$ uv tool install -e '.[cli]'
```

With pip: `python3.13 -m venv .venv && . .venv/bin/activate && pip install -e '.[cli]'`. To use the clone as a
library in another project's virtual environment, install it by path from there: `uv pip install -e
'/path/to/environment-store[postgres]'` or `pip install -e '/path/to/environment-store[postgres]'`.

## Optional extras

The core package depends only on `cryptography`. Everything else is an extra:

| Extra | What it adds | Dependencies | Needed for | uv | pip |
|---|---|---|---|---|---|
| *(none, core)* | Python library, encryption, the JSON, TOML and SQLite backends | `cryptography>=44` | `environment_store.load()`, `EnvironmentStore`, `json://`, `toml://`, `sqlite:///` connections | `uv add environment-store` | `pip install environment-store` |
| `cli` | the `envs` / `environment-store` command | `typer>=0.26` | every `envs` command | `uv tool install 'environment-store[cli]'` | `pip install 'environment-store[cli]'` |
| `postgres` | the PostgreSQL backend | `psycopg[binary]>=3.2` | `postgresql://` and `postgres://` connections, in the library and the CLI (including `envs migrate` on PostgreSQL) | `uv add 'environment-store[postgres]'`, or for the CLI `uv tool install 'environment-store[cli,postgres]'` | `pip install 'environment-store[postgres]'` |
| `tui` | the terminal UI | `textual>=8.2` | `envs tui` (needs `cli` as well) | `uv tool install 'environment-store[cli,tui]'` | `pip install 'environment-store[cli,tui]'` |
| `all` | all of the above | `typer`, `psycopg[binary]`, `textual` | everything | `uv tool install 'environment-store[all]'` | `pip install 'environment-store[all]'` |

An HTTP API, a web interface and AWS backends are planned as later extras (`api`, `web`, `aws`). They do not
exist yet.

**Combining extras.** List several extras in one pair of brackets, separated by commas:
`'environment-store[cli,postgres]'`. `uv tool install` replaces the tool's environment with exactly the extras you
name, so to add one, run the install again with the full list, for example
`uv tool install 'environment-store[cli,postgres,tui]'`. With `uv add`, adding the package again with more extras
updates the entry in `pyproject.toml`.

**A missing extra** gives a clear message and exit code 1 instead of an import error. For example, with only the
core package installed:

```console
$ envs --version
Error: this feature needs the optional 'cli' dependencies: pip install 'environment-store[cli]'
$ envs -c postgresql://localhost/app ls-store
Error: this feature needs the optional 'postgres' dependencies: pip install 'environment-store[postgres]'
```

The hint always names the pip command. With uv, install the tool again with the extra added
(`uv tool install 'environment-store[cli,postgres]'`), or `uv add 'environment-store[postgres]'` in a project.
`envs tui` without `tui` gives the same message for `'tui'`. In Python, the error is `MissingExtraError`, whose
`extra` attribute names the missing extra (`'postgres'`).

## Pre-releases on PyPI

If 2.0 is first published as a pre-release (for example `2.0.0rc1`), pin it so that uv and pip cannot pick 0.1:
`uv tool install 'environment-store[cli]>=2.0.0rc1'` or `pip install 'environment-store[cli]>=2.0.0rc1'`.

## Man page and tldr page

The wheel installs a man page as `share/man/man1/envs.1` (also as `environment-store.1`). After `pip install` or
`uv pip install` into an activated virtual environment, or in a uv project with `uv run man envs`, `man envs`
works. `uv tool install` links only the executables onto your `PATH`, so open the page by path:

```sh
man "$(uv tool dir)/environment-store/share/man/man1/envs.1"
```

The tldr page lives in the repository at [`docs/tldr/envs.md`](tldr/envs.md); it is not part of the tldr-pages
project yet. [Reference pages](cli.md#reference-pages-man-and-tldr) in the CLI guide has the details, including
`MANPATH`.

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
$ envs -h
Usage: envs [OPTIONS] COMMAND [ARGS]...

  Keep environment variables in named, optionally encrypted stores and load
  them anywhere.
...
$ python -c 'import environment_store; print(environment_store.__version__)'
2.0.0.dev0
```

`-h` and `--help` are the same, on `envs` and on every command.

Next: the [Quickstart](quickstart.md).
