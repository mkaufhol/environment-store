# Testing

Every change starts with a failing test, and the suite must keep 100 % line and branch coverage.
This page shows where tests go, which helpers to use and how to run part of the suite.

## Layout

| Directory | What it tests |
|---|---|
| `tests/unit/` | Pure code and the library, one subdirectory per layer: `core/`, `crypto/`, `formats/`, `config/`, `library/`, `service/`, `adapters/sql/`, plus `support/` for the test helpers themselves. The top-level files check the package as a whole (import rules, public API, extras, version) and the private TOML writer (`test_toml.py`). |
| `tests/contract/` | `AdapterContract`, the shared suite that every adapter runs. It has no tests of its own. |
| `tests/adapters/` | Each backend against real storage: `files/`, `sqlite/`, `postgres/`. |
| `tests/cli/` | The `envs` command in-process, grouped like the subpackages of `src/environment_store/cli/` (`stores/`, `variables/`, `exporting/`, `encryption/`, `completion/`), plus `foundation/` for its top-level modules (app, errors, options, prompts, runtime, …). |
| `tests/tui/` | The terminal UI, driven headless with Textual's Pilot. |
| `tests/docs/` | The documentation against the code (see [Documentation](documentation.md)). |
| `tests/support/` | Shared fakes, Hypothesis strategies and the CLI harness. |

**Where a test goes:**

- **A source module maps to a test module:** `src/environment_store/core/merge.py` is tested in
  `tests/unit/core/test_merge.py`.
- **Large modules split by topic:** `test_connection.py`, `test_connection_location.py`.
- **Property tests may get their own file:** `test_merge_properties.py`.
- **CLI tests are named after the command,** not the module: `tests/cli/stores/test_cp_store.py`
  tests `cli/stores/copying.py`.
- **`tests/` is a package.** Import helpers absolutely: `from tests.support.cli import CliHarness`.

## Writing a test

- **The name is the behaviour:** `test_write_store_with_stale_revision_raises_conflict`, not
  `test_write_store_2`. Every rule (a validation, an error, an exit code, a precedence) has a test
  that names it.
- **One behaviour per test.** Arrange, act and assert, separated by blank lines.
- **Input tables use `pytest.mark.parametrize`,** with `ids=` when the values are unreadable.
- **No test depends on another test** or on the order tests run in. Use `tmp_path` for files.
- **Round-trips use Hypothesis:** values through adapters, serializers, escaping, encryption.
  Reuse the strategies in `tests/support/strategies.py` instead of writing new ones: they already
  mix in hostile inputs such as `../x`, `café`, newlines and quotes.
- **Fakes, not mocks.** There is no `unittest.mock` in this repository. Replace a boundary with a
  fake or with `monkeypatch`; never mock the unit under test or a layer between two units.

### The fakes and helpers

| Helper | Use it for |
|---|---|
| `tests/support/memory_adapter.py` | `MemoryBackend` and `MemoryAdapter`, the in-memory reference adapter. The standard fake for core, service, library and TUI session tests. Subclass it to inject failures. |
| `tests/support/clock.py` | `FakeClock`, a controllable clock. Pass it wherever `clock=` is accepted. |
| `tests/support/kdf.py` | `CheapKdf`, tiny Argon2id parameters. **Always** pass it as `kdf_params_factory` for passphrase stores, or tests take seconds each. |
| `tests/support/strategies.py` | Hypothesis strategies for names, values, records, timestamps and cipher metadata. |
| `tests/support/cli.py` | `CliHarness`, the CLI test harness. Its module docstring is its manual. |
| `tests/unit/service/conftest.py` | Fault-injecting adapters: `UntouchableAdapter` proves that validation runs before any I/O, and `RacingAdapter` injects a concurrent write. |

### CLI tests

Arrange and assert through the library, act through the CLI:

```python
def test_rm_deletes_the_variable(cli: CliHarness) -> None:
    library = cli.store()
    library.create_store("dev")
    library.set_many("dev", {"A": "1", "B": "2"})

    result = cli.invoke("rm", "-s", "dev", "A")

    assert_exit(result, 0)
    assert cli.store().variables("dev") == {"B": "2"}
    assert result.stdout == ""
```

- **Fixtures.** The `cli` fixture runs a test once per backend (JSON, TOML and SQLite). Use it for
  the main paths. Use `cli_json` for error cases that don't depend on the backend.
- **How `invoke` runs.** `cli.invoke(...)` runs the real typer app in-process with `-c <connection>`
  prepended. Pass `connection=False` to leave it out.
- **Prompts.** `RecordingPrompter(*answers)` scripts them. With no answers, any prompt fails the
  test. Use `stdin_tty=True` / `stdout_tty=True` to pretend to be a terminal.
- **Exit codes.** Prefer `assert_exit(result, code)` over comparing `exit_code`: on a mismatch it
  prints stdout, stderr and the exception.
- **`envs run`.** It records its `exec` call in `cli.exec_calls` instead of replacing the test
  process.
- **Concurrent changes and failures.** Pass `opener=cli.hooked_opener(before=...)` to `cli.invoke`
  to write concurrently just before the command's own write (exit 5). Use
  `after={"write_store": raising(error)}` to simulate a failure after the commit.
- **Hypothesis.** Inside `@given`, use `with temporary_cli("json") as cli:`. Function fixtures are
  not reset between examples.

### TUI tests

`tests/tui/pilot.py` runs the app headless with `run_app(store, scenario)`. A scenario is an async
function that receives the Pilot and the app. Read the screen with `rows`, `footer` and
`notifications`, and fill inputs with `set_input`. The TUI tests use plain `asyncio.run`; there is
no pytest-asyncio.

## Running tests

```bash
uv run pytest tests/unit/core/test_merge.py              # one file
uv run pytest "tests/cli/variables/test_set.py::test_x"  # one test (quote ids with [params])
uv run pytest -k "revision and not postgres"             # by keyword
uv run pytest -m "not postgres"                          # everything but the PostgreSQL tests
HYPOTHESIS_PROFILE=ci uv run pytest                      # Hypothesis settings as in CI
uv run coverage run -m pytest && uv run coverage report  # the full run, as in the definition of done
```

- **Coverage for a subset.** Limit the report, or it fails the 100 % threshold:
  `uv run coverage report --include='src/environment_store/core/*'`.
- **No parallel runner.** The suite runs in series. The full run takes a few minutes; the
  PostgreSQL tests add the cluster start-up.
- **Strict pytest.** `[tool.pytest.ini_options]` sets `filterwarnings = ["error"]`, `--strict-markers`
  and `xfail_strict`. Any warning fails a test, including a deprecation warning from a dependency.
  Markers must be registered in `[tool.pytest.ini_options] markers`.
- **Read the skip summary.** `-ra` prints why tests were skipped, so check it when a group of tests
  silently disappears.

### Hypothesis profiles

`tests/conftest.py` registers two profiles, selected with `HYPOTHESIS_PROFILE`:

- `default`: no deadline. This is the local default.
- `ci`: 200 examples, derandomized, and no example database.

CI uses `ci`, so set it locally to reproduce a CI failure.

The same file has the autouse fixture `_no_key_variables`. It removes every `ENV_STORE_KEY_*`
variable, so your shell can't leak a key into a test.

### PostgreSQL

The PostgreSQL tests carry the `postgres` marker and need a server. `tests/adapters/postgres/server.py`
gets one in two ways:

1. **`ENV_STORE_TEST_POSTGRES_URL`:** a superuser URL of a throwaway server. CI points it at a
   `postgres` service container. Never point it at a server that holds data you care about: the
   tests create and drop databases and roles.
2. **Otherwise, a private cluster.** `initdb` and `pg_ctl` from your `PATH` start one in a
   temporary directory, with trust authentication, no TCP listener and a Unix socket under `/tmp`.
   It is stopped at the end of the run. Each test gets a fresh database.

Without either, the PostgreSQL tests **fail** with a hint; they don't skip. Use `-m "not postgres"`
while you work on something else. The definition of done needs them, because without them the
PostgreSQL adapter is not covered.

Every module in `tests/adapters/postgres/` that needs the server sets
`pytestmark = pytest.mark.postgres`. `tests/adapters/postgres/test_markers.py` lists every module
of the directory, the marked ones and the ones without a server. It fails when a module is unmarked,
and when you add a module without adding it to the matching list.

### Other environment-dependent tests

- **Shell tests.** `tests/cli/completion/test_shells.py` runs the generated completion scripts in
  zsh and bash. It is skipped when the shell or the installed `envs` command is missing; `uv sync`
  installs the command.
- **Entry points.** `tests/cli/foundation/test_entry_points.py` reads the installed package
  metadata.
- **Man page lint.** It runs only when `mandoc` is installed.
- **Root and platform.** A few tests skip when run as root (file permission checks) or on
  platforms without `exec`.

## Coverage

- **What is measured.** Coverage is measured for `environment_store` with branch coverage, and
  `fail_under = 100`.
- **Allowed exclusions.** The only ones are the `exclude_also` patterns in `pyproject.toml`:
  `if TYPE_CHECKING:`, `...`, `raise NotImplementedError` and
  `if sys.platform == "win32":`.
- **Subprocesses don't count.** Code that runs only in a subprocess is not measured, because there
  is no parallel or subprocess coverage. That covers the fresh-interpreter import tests, the
  spawned workers in the file adapter tests and the shell tests. Every line also needs an
  in-process test.
- **Code you can't cover** is a design smell. Inject the boundary (clock, OS call, prompter) so a
  test can reach the branch, instead of excluding it.

## Tests that guard the architecture

These tests fail on structural mistakes, not on behaviour. Know them before you add a module:

| Test | Fails when |
|---|---|
| `tests/unit/test_import_direction.py` | a module imports from a layer it may not use, or a new package or adapter subpackage has no entry in `ALLOWED_IMPORTS`, see [Architecture](architecture.md#layers-and-import-rules) |
| `tests/unit/test_package.py` | the public API, `__all__`, the lazy imports or `py.typed` are out of step, or a module can't be imported on its own |
| `tests/unit/test_extras.py` | the `all` extra is not exactly the union of the other extras, or a pinned extra changed |
| `tests/unit/support/test_adapter_contract.py` | the contract's property tests change without updating its list |
| `tests/cli/test_command_table.py` and `tests/cli/completion/test_protocol.py` | a command is added or removed without updating their expected command sets |
| `tests/cli/foundation/test_errors.py` | an error class has no expected exit code |
| `tests/cli/foundation/test_typer_boundary.py` | a module imports click or typer's private click at runtime |
| `tests/adapters/postgres/test_markers.py` | a module in `tests/adapters/postgres/` is unmarked, or missing from the test's lists of marked and server-less modules |
