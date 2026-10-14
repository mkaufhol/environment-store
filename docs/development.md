# Development

How to work on environment-store itself.

- [Setup](#setup)
- [Project layout](#project-layout)
- [Architecture: one shared layer](#architecture-one-shared-layer)
- [Everyday commands](#everyday-commands)
- [Tests](#tests)
- [Adding a feature](#adding-a-feature)
- [Adding a storage adapter](#adding-a-storage-adapter)
- [Database migrations](#database-migrations)
- [Running the CLI or TUI from a clone](#running-the-cli-or-tui-from-a-clone)
- [Docs and the agent skill](#docs-and-the-agent-skill)

## Setup

The project uses [uv](https://docs.astral.sh/uv/) and needs Python 3.12 or newer.

```bash
git clone https://github.com/mkaufhol/environment-store
cd environment-store
uv sync                 # installs the dev, testing and stubs groups
pre-commit install      # run the quality checks on every commit
```

The dependency groups in `pyproject.toml`:

| Group | Contents |
|---|---|
| `dev` | ruff, ty, pre-commit, bandit, tox, yoyo-migrations |
| `testing` | pytest, moto, coverage, sqlalchemy, psycopg, textual |
| `stubs` | boto3-stubs |

The optional extras for users (`aws`, `postgres`, `tui`, `full`) are described in
[Installation](installation.md). Keep the `full` extra equal to the union of the others.

## Project layout

```
src/environment_store/
├── core/                      # the shared layer, no I/O of its own
│   ├── manager.py             # EnvironmentStoreManager: the public API
│   ├── hierarchy.py           # level names, path <-> kwargs helpers
│   ├── abstract_adapter.py    # contract every backend implements
│   ├── schemas.py             # Variable, TransferResult, ...
│   ├── decorators.py          # validate_hierarchy
│   └── exceptions.py
├── adapters/
│   ├── json/                  # JsonFileAdapter
│   ├── postgresql/            # PostgreSQLAdapter, migrations, sqlc-generated queries
│   └── aws/
│       ├── ssm_parameter_store/
│       └── secrets_manager/
├── cli.py                     # environment-store command
└── tui/                       # Textual app
tests/                         # mirrors src/
docs/                          # this documentation
.claude/skills/environment-store-cli/SKILL.md   # skill for LLM agents using the CLI
```

## Architecture: one shared layer

The CLI, the TUI and any future frontend (an API, a web app) are **thin presentation layers** over
`EnvironmentStoreManager`:

```
 CLI (cli.py)     TUI (tui/)     future API / web app
        \             |             /
         \            |            /
          EnvironmentStoreManager  (core/manager.py + core/hierarchy.py)
                      |
               AbstractAdapter
        /        |         |          \
   JSON file  PostgreSQL  SSM   Secrets Manager
```

**All logic lives in the core layer.** That includes hierarchy rules, listing child levels (`get_child_levels`),
merging parent variables (`get_resolved_variables`), walking and copying stores (`iter_levels`, `import_from`),
and counting and deleting levels (`count_level`, `delete_level`), including the safety rule that deleting a level
requires its exact name as `confirm`.

A frontend should only:

1. parse its input (arguments, keys, HTTP requests),
2. call the manager,
3. render the result or the error.

If you catch yourself writing a loop over levels, a merge, or a validation rule in `cli.py` or `tui/app.py`, it
belongs in the manager so every frontend gets it and there is nothing to keep in sync.

Keep the CLI and TUI feature-equivalent. For example `x` in the TUI is `delete-level` in the CLI, and `n` is `set`
on a new path. Bulk administration commands (`import`, `transfer`, `migrate`) are CLI-only.

## Everyday commands

```bash
uv run pytest                  # tests
uv run ruff check              # lint
uv run ruff format             # format
uv run ty check                # type check
uv run bandit -c pyproject.toml -r src   # security lint (also runs in pre-commit)
uv build                       # build sdist and wheel into dist/
```

Pre-commit runs: YAML check, end-of-file fixer, trailing whitespace, `ruff check`, `ruff format`, `uv-lock`, `ty` and
`bandit`. A commit is rejected if one fails; fix the issue (some hooks fix files for you), `git add` again and commit.

`ruff` and `ty` skip the sqlc-generated files `adapters/postgresql/queries.py` and `models.py`.

`tox` runs the suite on all supported Python versions (`uv run tox`); missing interpreters are skipped.

## Tests

```bash
uv run pytest                                   # everything
uv run pytest tests/environment_store/core      # one area
uv run pytest -k delete_level                   # by name
```

- `tests/` mirrors `src/`. The AWS adapters are tested against [moto](https://docs.getmoto.org/), so no AWS account
  is needed.
- The TUI is tested headlessly with Textual's `run_test()` pilot (`tests/environment_store/test_tui.py`).
- The CLI is tested by calling `main([...])` with a temporary JSON file (`tests/environment_store/test_cli.py`).
- Every adapter runs the same shared behavioural suite, `AdapterContract` in
  `tests/environment_store/adapters/contract.py`. See [Adding a storage adapter](adding-an-adapter.md#4-test-it-with-the-shared-contract).

### PostgreSQL tests

They are skipped unless `ENVIRONMENT_STORE_TEST_POSTGRES_URL` points to a **throwaway database**. The tests apply
the migrations and **truncate the `environment_store` table between tests**, so never point it at real data:

```bash
createdb env_store_test
export ENVIRONMENT_STORE_TEST_POSTGRES_URL=postgresql+psycopg://postgres:password@localhost:5432/env_store_test
uv run pytest tests/environment_store/adapters/postgresql
```

## Adding a feature

1. **Core first.** Add the method to `EnvironmentStoreManager` (use `@validate_hierarchy` for methods that take
   hierarchy arguments, and call them with keywords, because the decorator only sees keyword arguments). Reuse
   helpers from `core/hierarchy.py`. Add unit tests in `tests/environment_store/core/`.
2. **CLI.** Add `cmd_<name>` and its sub-parser in `cli.py`. Reuse `_hierarchy_parser()` for `-o/-p/-e/-s` and
   `_hierarchy(args)` to forward them. Print data to stdout, messages to stderr, and return one of the documented
   exit codes. Add tests that call `main([...])`.
3. **TUI.** Add a binding and action in `tui/app.py` that calls the same manager method. Add a pilot test.
4. **Docs.** Update [cli.md](cli.md), [tui.md](tui.md) and [python-usage.md](python-usage.md), and the agent skill
   (see below).
5. Run `uv run pytest`, `uv run ruff check`, `uv run ty check`.

## Adding a storage adapter

The full guide is **[Adding a storage adapter](adding-an-adapter.md)**: the contract, a complete worked example,
design decisions, packaging, wiring into the CLI, and docs. In short:

1. Subclass `AbstractAdapter` in `adapters/<name>/` and implement its ten abstract methods; levels are implicit and
   disappear with their last variable.
2. Run the shared contract tests (`tests/environment_store/adapters/contract.py`) against it by subclassing
   `AdapterContract` in your test module.
3. Add an optional extra (and add it to `full`), import the SDK lazily, export the class.
4. Register it in `cli.py` (`BACKENDS`, `_add_backend_options`, `build_manager`, `_backend_identity`).
5. Document it in [backends/](backends/README.md), [installation.md](installation.md) and [cli.md](cli.md).

## Database migrations

The PostgreSQL schema is managed with [yoyo](https://ollycope.com/software/yoyo/latest/). Migrations live in
`src/environment_store/adapters/postgresql/migrations/` and ship inside the package, so users apply them with
`environment-store migrate`.

Create a new migration (SQL format, with a rollback file):

```bash
cd src/environment_store/adapters/postgresql
uv run yoyo new --sql -m "describe the change" migrations
```

Edit the generated `<id>.sql` and `<id>.rollback.sql` files. Never edit a migration that has been released; add a new
one instead.

Apply migrations with the yoyo CLI while developing: copy `yoyo-database-example.ini` to `yoyo-database.ini`
(git-ignored), put your database URL in it and run

```bash
src/environment_store/adapters/postgresql/scripts/init_database.sh
```

### Regenerating the typed queries

`queries.py` and `models.py` are generated by [sqlc](https://sqlc.dev/) from `queries.sql` and the live schema. After
changing a migration or `queries.sql`:

```bash
# needs sqlc and pg_dump on PATH, and yoyo-database.ini pointing to a migrated database
src/environment_store/adapters/postgresql/scripts/generate_sqlc.sh
```

This dumps the schema to `schema.sql` and runs `sqlc generate`. Commit the regenerated files. Never edit
`queries.py` or `models.py` by hand.

## Running the CLI or TUI from a clone

Inside the clone, `uv run` uses the project environment:

```bash
uv run environment-store --backend json --json-file ./store.json list
uv run environment-store --backend json --json-file ./store.json tui
```

From anywhere else, `uvx` can run the clone without installing it. Quote the requirement (the `[full]` and the spaces
would otherwise be interpreted by your shell):

```bash
uvx --from "environment-store[full] @ path/to/repo" environment-store \
  --backend json --json-file ./store.json list -o acme

uvx --from "environment-store[full] @ path/to/repo" environment-store \
  --backend json --json-file ./store.json tui
```

Use `[aws]`, `[postgres]` or `[tui]` instead of `[full]` to install only what you need.

**Stale code?** By default uv builds a path dependency once and reuses that build until `pyproject.toml` changes. The
version number does not change while you develop either, so `uvx` can keep running old code, and `--refresh` and
`--reinstall` do not help. This project therefore sets `cache-keys` in `[tool.uv]` (`pyproject.toml`), so uv
rebuilds whenever a `.py` or `.sql` file under `src/` changes and plain `uvx` always runs your latest code. If you
ever see old behaviour anyway (for example on a branch without that setting), use one of these:

```bash
uv run --project path/to/repo --all-extras environment-store --backend json --json-file ./store.json list
uv tool install --editable "path/to/repo[full]"       # then just run: environment-store ...
uvx --no-cache --from "environment-store[full] @ path/to/repo" environment-store -h   # slow: rebuilds everything
```

`uv run --project` and an editable `uv tool install` always use your working tree, which makes them the best choice
for daily development.

To test the built package in a separate virtual environment:

```bash
uv build
uv pip install "dist/environment_store-0.1.0-py3-none-any.whl[full]"
```

To use the clone from another project while you edit it:

```bash
uv add --editable "environment-store[full] @ path/to/repo"
```

## Docs and the agent skill

- The documentation lives in `docs/`; the [README](../README.md) only summarises it and links here. When behaviour
  changes, update the relevant guide in the same commit, and keep command examples runnable.
- [`.claude/skills/environment-store-cli/SKILL.md`](../.claude/skills/environment-store-cli/SKILL.md) teaches LLM
  agents to use the CLI efficiently and safely. Update it whenever a CLI command, option, exit code or safety rule
  changes. It deliberately tells agents not to use the interactive `tui`.

## Releasing

Releases are published from GitHub Actions with PyPI trusted publishing, so no API token is stored.

One-time setup:

1. On [PyPI](https://pypi.org/manage/account/publishing/) and [TestPyPI](https://test.pypi.org/manage/account/publishing/)
   add a pending trusted publisher: owner `mkaufhol`, repository `environment-store`,
   workflow `release.yml`, environment `pypi` (PyPI) or `testpypi` (TestPyPI).
2. In the GitHub repository settings create the matching `pypi` and `testpypi` environments.
   Optionally require a reviewer on `pypi`.

Per release:

1. Bump `version` in `pyproject.toml`, add a section to `CHANGELOG.md`, run `uv lock` and merge to `main`.
2. Optional dry run: run the **Release** workflow manually with target `testpypi`.
3. Tag and push: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`.
   The workflow checks that the tag matches the package version, builds, publishes to PyPI
   and creates a GitHub release (marked as pre-release for `rc`, `a`, `b` and `dev` versions).
