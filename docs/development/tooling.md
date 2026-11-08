# Tools

Everything runs through [uv](https://docs.astral.sh/uv/). There is no Makefile, tox or nox setup:
the commands below are the whole toolchain, and the definition of done in
[`CONTRIBUTING.md`](../../CONTRIBUTING.md#1-toolchain) lists the ones that must pass.

## uv

| Task | Command |
|---|---|
| Install the environment | `uv sync` (CI uses `uv sync --locked`, which fails if `uv.lock` is out of date) |
| Run a tool | `uv run <tool>`, for example `uv run pytest` |
| Try another Python | `uv sync --python 3.13`, then `uv run --python 3.13 pytest` |
| Update the lock file | `uv lock` (the pre-commit hook does it too) |
| Build the distributions | `uv build`, then `uvx twine check dist/*` |
| Show or set the version | `uv version`, `uv version --short`, `uv version X.Y.Z` |

What `uv sync` installs:

- **The project itself,** with the `envs` and `environment-store` commands in `.venv/bin`.
- **The `dev` group:** ruff, ty, bandit and pre-commit.
- **The `testing` group:** pytest, coverage, Hypothesis, python-dotenv (for the dotenv
  compatibility tests) and the dependencies of every extra (psycopg, typer, textual), so ty and the
  tests see all optional code.

`[tool.uv] default-groups` selects both groups, so you never need `--all-extras` for development.

### Dependencies

The core depends on `cryptography` only. A new runtime dependency is a design decision; discuss it
before you add one. When it is decided:

| Kind | Command | Also update by hand |
|---|---|---|
| A new optional extra | `uv add --optional <extra> <package>` | the `all` extra and the `testing` group, with the same requirement string |
| A test library | `uv add --group testing <package>` | |
| A development tool | `uv add --group dev <package>` | the pre-commit hook version, if the tool has one |

`tests/unit/test_extras.py` checks that `all` is exactly the union of the other extras and pins the
`cli` and `tui` requirements. Change those tests deliberately when you change a floor.

## ruff

```bash
uv run ruff format .        # format
uv run ruff check --fix .   # lint and apply safe fixes
```

The configuration is in `[tool.ruff]` in `pyproject.toml`: the target is Python 3.12, the line
length is 100, and the docstring convention is Google. [Code conventions](conventions.md) explains
the rules you will meet most. The pre-commit hook and `uv.lock` must use the same ruff version, so
bump both together.

## ty

```bash
uv run ty check --error-on-warning
```

- **The checker.** [ty](https://docs.astral.sh/ty/) checks `src/` and `tests/` against Python 3.12
  (`[tool.ty.environment]`).
- **Warnings are errors.** Always pass `--error-on-warning`; that flag, not a config file, makes
  warnings errors.
- **Suppressions.** A `# ty: ignore[rule]` needs the rule and a reason. Usually a cast is wrong
  too: narrow with `isinstance` or `assert` instead, as the tests do with
  `assert _ZSH is not None`.

## bandit

```bash
uv run bandit -q -c pyproject.toml -r src
```

- **What it checks.** Bandit checks `src/` for security problems. ruff's `S` rules overlap with it;
  both run.
- **Tests are excluded.** `[tool.bandit]` excludes `tests/`, where `assert` and subprocess calls are
  normal.
- **Fix findings, don't suppress them.** A justified suppression names the rule and the reason:
  `# nosec B603`, usually next to the matching `# noqa: S603`.

## pre-commit

```bash
uv run pre-commit install          # once per clone
uv run pre-commit run --all-files  # all hooks on all files
```

The hooks (`.pre-commit-config.yaml`):

- YAML and TOML syntax, trailing whitespace and end of file
- ruff check and ruff format
- `uv lock`
- ty
- bandit

**The hooks do not run the tests.** Run the test and coverage steps of the definition of done
yourself before you push.

The ty hook checks the whole working tree, including untracked files. If a commit is refused
because of a file you haven't staged yet, stage it with the change it belongs to, or stash it.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes to `main`, `feature/**` and `v2/**` branches, and on
every pull request. Name a branch `feature/<topic>` if you want CI on every push before you open a
pull request.

| Job | What it runs |
|---|---|
| `lint` | ruff format check, ruff check, ty, bandit |
| `test` | `coverage run -m pytest` and `coverage report` on every supported Python, with a PostgreSQL service and `HYPOTHESIS_PROFILE=ci` |
| `build` | `uv build` and `twine check` |

Coverage must reach 100 % on every Python version in the matrix. CI runs on Linux only.

The `test` matrix must include the minimum Python from `requires-python`, and the classifiers, ruff
and ty must start at it. `tests/docs/test_documentation.py` checks all of them, the documented
minimum and the version's changelog entry ("Python X.Y or newer"). Raising the minimum Python
therefore means updating `pyproject.toml`, the CI matrix, the documentation and `CHANGELOG.md`
together.

## Releases

Releases are published by `.github/workflows/release.yml` with PyPI trusted publishing. Nobody
uploads by hand. [`CONTRIBUTING.md`](../../CONTRIBUTING.md#9-releasing) has the steps.

In short:

1. Update `CHANGELOG.md` and run `uv version X.Y.Z`.
2. Update every place that shows the version:
   - documented sample output (`tests/docs` fails until you do);
   - the date and version in the man page header;
   - `tests/unit/test_version.py`.
3. Merge to `main`, then tag `vX.Y.Z` on `main` and push the tag.

The workflow refuses a tag that is not on `main`, doesn't match the package version, or has no
changelog entry.

## Packaging

- **Build backend.** The package builds with `uv_build`.
- **What the wheel contains.** `src/environment_store`, including `py.typed`, and the man pages
  from `docs/man` as data files, so `man envs` works after installation. Tests and docs are not in
  the wheel.
- **Entry points.** `envs` and `environment-store` both run `environment_store.cli:main`. Keep
  `cli/__init__.py` free of typer imports (a test checks it), so a missing `cli` extra gives a clean
  error.
