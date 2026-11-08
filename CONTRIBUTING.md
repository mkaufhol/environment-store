# Contributing to Environment Store

These rules are **binding** for all code in this repository, written by humans or agents. When a rule here
conflicts with convenience, the rule wins.

## 1. Toolchain

| Tool | Purpose | Command |
|---|---|---|
| uv | environments, dependencies, builds | `uv sync`, `uv build` |
| ruff | formatting and linting | `uv run ruff format .`, `uv run ruff check .` |
| ty | type checking, warnings are errors | `uv run ty check --error-on-warning` |
| pytest + coverage | tests, 100 % line **and** branch coverage | `uv run coverage run -m pytest && uv run coverage report` |
| bandit | security linting of `src/` | `uv run bandit -q -c pyproject.toml -r src` |
| pre-commit | runs all of the above on commit | `uv run pre-commit run --all-files` |

**Definition of done** for every change — all must pass locally and in CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check --error-on-warning
uv run bandit -q -c pyproject.toml -r src
uv run coverage run -m pytest
uv run coverage report        # fails below 100 % (line + branch)
```

## 2. Test-driven development

1. **Red:** write a failing test for the next small piece of the behaviour being built. Run it and see it fail for
   the right reason.
2. **Green:** write the minimum production code to make it pass.
3. **Refactor:** clean up code and tests with all tests green.

Rules:

- No production code without a test that required it. Every behaviour rule (a validation, an error, an exit code,
  a precedence order) has at least one test that names it.
- Tests describe behaviour, not implementation: `test_write_store_with_stale_revision_raises_conflict`, not
  `test_write_store_2`. Arrange / act / assert, one behaviour per test.
- Use `pytest.mark.parametrize` for input tables, `tmp_path` for files, fixtures for setup. No test depends on
  another test's state or on execution order.
- Use **Hypothesis** property tests for round-trips (values through every adapter, serializers, escaping,
  encryption).
- No network access in tests. PostgreSQL tests use a throwaway local cluster, never a shared server.
- Every adapter passes the shared **adapter contract suite** (`tests/contract/`) in addition to its own tests.
- 100 % line and branch coverage. `# pragma: no cover` is forbidden except for the patterns configured in
  `[tool.coverage.report] exclude_also` (`if TYPE_CHECKING:`, `...` protocol bodies, `raise NotImplementedError`,
  and platform branches guarded by `sys.platform == "win32"`). Untestable code is a design smell: restructure it.
- Mock only at system boundaries (clock, randomness, terminal, OS calls). Never mock the unit under test or the core
  between layers; prefer fakes (e.g. the in-memory test adapter) over mocks.

## 3. Typing

- **Type hint everything:** every function and method parameter and return value (including `-> None`), every
  module-level and class attribute, in `src/` **and** `tests/` (fixtures and test functions included). Enforced by
  ruff `ANN` and ty.
- `ty check --error-on-warning` must be clean. No `# type: ignore` / `# ty: ignore` without a specific rule code
  and a comment explaining why.
- No `Any` in public signatures. Inside the code, `Any` is allowed only at untyped boundaries (e.g. parsed JSON),
  immediately narrowed and validated.
- Use modern syntax (Python 3.13+): `list[str]`, `X | None`, PEP 695 generics (`def f[T](x: T) -> T`), `type`
  aliases, `typing.Self`, `typing.override` on overriding methods, `Literal` and `enum.StrEnum` for closed sets.
- Interfaces are `typing.Protocol`s; implementations do not need to inherit from them.
- Ship `py.typed`.

## 4. Code design

- **Value objects** are `@dataclass(frozen=True, slots=True, kw_only=True)`; collections inside them are immutable
  (`tuple`, `frozenset`, `types.MappingProxyType` or copied on construction). Validate in `__post_init__`.
- **Pure core, I/O at the edges.** Validation, merging, serialization and crypto are pure functions or small
  classes without I/O. Adapters and frontends do the I/O.
- Small functions with one job; no module over ~400 lines; no function over ~40 lines without a good reason.
- **Keyword-only booleans** (ruff `FBT`): `encrypt(..., *, overwrite: bool = False)`.
- No mutable default arguments, no global mutable state, no singletons. Dependencies are passed in (clock, random
  source, prompt functions), which keeps code testable.
- `pathlib.Path` for paths, context managers for every resource (files, locks, connections), adapters implement
  `close()` and `__enter__` / `__exit__`.
- Timestamps are timezone-aware UTC `datetime`s.
- Public modules define `__all__`. Private helpers start with `_`. Absolute imports only.
- Optional dependencies (`psycopg`, `typer`, `textual`) are imported lazily inside the code path that needs them;
  a missing extra raises `MissingExtraError` with the `pip install` hint.
- Type-only imports go in `if TYPE_CHECKING:` blocks (ruff `TC`).

## 5. Errors and logging

- All library errors derive from `EnvironmentStoreError` (`environment_store.core.errors`). Raise the most specific
  one; chain with `raise ... from err`; never `except Exception:` without re-raising; never bare `except:`.
- Error messages are built in a variable before raising (ruff `EM`) and say what failed and how to fix it.
- Library code never calls `print`, `sys.exit` or `input`; only the CLI/TUI layers talk to the terminal.
- Logging via `logging.getLogger(__name__)`; the library adds no handlers.

## 6. Security

- **bandit** runs in pre-commit and CI over `src/`; ruff's `S` (flake8-bandit) rules are enabled as well. Findings
  are fixed, not suppressed; a suppression (`# nosec B…`) needs the rule id and a justification.
- **Secrets never leak:** keys, passphrases and decrypted values never appear in logs, exception messages, `repr`s
  or tracebacks. Secret-bearing fields use `field(repr=False)` or the `Secret` wrapper with a redacted `repr`.
- Randomness for keys, nonces and salts comes from `secrets` / `os.urandom` only.
- Key files are created with mode `0600` and never overwritten (`O_CREAT | O_EXCL`).
- SQL uses parameters only; identifiers (the Postgres schema name) must match `^[a-z_][a-z0-9_]{0,62}$` and are
  quoted with `psycopg.sql.Identifier`. No string-formatted SQL with user input.
- No `eval`, `exec`, `pickle`, `shell=True` or `yaml.load`.
- Dependencies are pinned through `uv.lock`; new runtime dependencies need a deliberate decision (the core depends
  on `cryptography` only).

## 7. Style and documentation

- `ruff format` (line length 100). The ruff rule set in `pyproject.toml` is the style guide; do not disable rules
  per file without a comment.
- Google-style docstrings on every public module, class, function and method (ruff `D`, `convention = "google"`).
  Tests need no docstrings. Comments explain *why*, not *what*.
- Comments and docstrings explain the reason directly instead of pointing to external documents, e.g.
  `# Ciphertext is bound to the store name, so a copy must be re-sealed.`

## 8. Git

- Branch per change off `main`.
- Small commits with an imperative subject line (`Add merge logic for ordered stores`) and a body explaining why.
- Never commit secrets, key files, `.env` files or coverage output.
- Record user-visible changes under `## [Unreleased]` in `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).

## 9. Releasing

Releases are published from `main` by the Release workflow (`.github/workflows/release.yml`) with PyPI trusted
publishing; nobody uploads by hand.

1. In `CHANGELOG.md`, turn `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`, add a new empty `## [Unreleased]`
   above it and update the compare links at the bottom.
2. Set the version: `uv version X.Y.Z` (updates `pyproject.toml` and `uv.lock`), and update documented sample
   output that shows the version (`tests/docs` fails until you do).
3. Merge to `main` through a pull request.
4. Optional: run the Release workflow by hand with target `testpypi` and try the result:
   `uvx --find-links https://test.pypi.org/simple/environment-store/ --from 'environment-store[cli]==X.Y.Z' envs --version`.
   This takes only `environment-store` from TestPyPI and every dependency from PyPI; the pin makes it fail
   instead of falling back to an older release on PyPI. Before the first run, add a pending trusted publisher
   for this repository, `release.yml` and the `testpypi` environment on TestPyPI.
5. Tag the release commit on `main` and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.

The workflow refuses a tag that is not on `main`, whose name does not match the package version, or that has no
`## [X.Y.Z]` entry in `CHANGELOG.md`. It then builds, checks and publishes the distributions to PyPI and creates
the GitHub release with the files attached (marked as a pre-release for `rc`, `a`, `b` and `dev` versions).
