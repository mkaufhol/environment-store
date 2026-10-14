# Installation

Requires Python 3.12 or newer.

## Extras

The core package only depends on `pydantic` and includes the JSON file backend, the CLI and the Python API.
Everything else is an optional extra, so you only install what you use:

| Extra      | Adds                                                                        | Needed for |
|------------|-----------------------------------------------------------------------------|------------|
| _(none)_   | core, `JsonFileAdapter`, CLI                                                | local files |
| `aws`      | `boto3`                                                                     | `ssm`, `secretsmanager` backends |
| `postgres` | `psycopg`, `sqlalchemy`, `yoyo-migrations`                                  | `postgres` backend and `migrate` |
| `tui`      | [`textual`](https://textual.textualize.io/)                                 | `environment-store tui` |
| `full`     | all of the above                                                            | everything |

Without the matching extra, using a backend or the TUI fails with a message that names the missing extra.

## With uv

Add it to a uv project (updates `pyproject.toml` and the lockfile):

```bash
uv add environment-store                  # core + JSON file backend
uv add "environment-store[aws]"           # + AWS backends
uv add "environment-store[postgres]"      # + PostgreSQL backend
uv add "environment-store[aws,postgres]"  # several extras
uv add "environment-store[full]"          # all extras
```

Without a uv project (quick script, existing virtual environment) use the pip interface:

```bash
uv pip install "environment-store[full]"
```

## With pip

```bash
pip install "environment-store[full]"
```

## From the repository

If the package is not available on an index you can use, install straight from git:

```bash
uv add "environment-store[full] @ git+https://github.com/mkaufhol/environment-store"
```

Pin a branch, tag or commit by appending `@<ref>`:

```bash
uv add "environment-store[full] @ git+https://github.com/mkaufhol/environment-store@v0.1.0"
```

## Run the CLI or TUI without installing

[`uvx`](https://docs.astral.sh/uv/guides/tools/) runs the command in a temporary environment:

```bash
uvx --from "environment-store[tui]" environment-store --backend json --json-file ./store.json tui
```

To run a local clone this way, see [Development](development.md#running-the-cli-or-tui-from-a-clone).

## Verify the installation

```bash
environment-store --help
python -c "import environment_store; print(environment_store.__version__)"
```

The CLI is also available as `python -m environment_store`.

## Next

[Quickstart](quickstart.md) · [Storage backends](backends/README.md)
