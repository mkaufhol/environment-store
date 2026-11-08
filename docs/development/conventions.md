# Code conventions

[`CONTRIBUTING.md`](../../CONTRIBUTING.md) is the rule book. This page shows how the rules look in
this code base and which tool enforces each one. When code here differs from an example below,
follow `CONTRIBUTING.md`.

## Formatting and linting

- **Formatter.** `ruff format` with a line length of 100. Docstring code blocks are formatted too.
- **Linter.** `ruff check` runs with a wide rule set and **no global ignore list** (`[tool.ruff.lint]`
  in `pyproject.toml`). Some of the rules you will meet:

  | Rule | What it means here |
  |---|---|
  | `ANN` | every parameter and return value is annotated, tests included |
  | `D` (Google convention) | every public module, class, function and method has a docstring (not tests) |
  | `FBT` | booleans are keyword-only |
  | `EM`, `TRY` | an error message is built in a variable before `raise` |
  | `S`, `BLE` | the flake8-bandit rules; no blind `except Exception` |
  | `DTZ` | no naive `datetime` |
  | `T20` | no `print` |
  | `TC` | type-only imports go into `if TYPE_CHECKING:` |
  | `TID` | absolute imports only, in `tests/` too |
  | `ERA` | no commented-out code |

- **Tests.** `tests/**` relaxes only `S101` (plain `assert`), `D` (no docstrings) and `PLR2004`
  (literal numbers in comparisons).
- **Types.** `ty check --error-on-warning` must be clean. The strictness comes from the flag: a
  bare `ty check` is weaker than the definition of done.
- **Security.** `bandit` checks `src/`; see [Tools](tooling.md#bandit).

## Suppression comments

A suppression is a last resort. Restructure the code first. When a suppression is right, it names
the exact rule and gives the reason after it:

```python
def get_variable(  # noqa: PLR0913 - one parameter per argument and option
variables=variables,  # ty: ignore[invalid-argument-type] - validated by StoreRecord
import subprocess  # nosec B404  # Windows has no exec(); used by run's fallback only
completed = subprocess.run(command, env=env, check=False)  # noqa: S603  # nosec B603
```

- **Common, accepted cases:**
  - `PLR0913` on CLI callbacks, which take one parameter per option.
  - `FBT001` on typer and textual callbacks, whose boolean parameters the framework passes.
  - `S603` (with `# nosec B603`) on a subprocess call with an argv list and no shell, as in the
    Windows fallback of `envs run`.
  - `BLE001` in shell completion (`cli/completion/`), where any failure means "no candidates",
    because completion must never fail visibly.
  - `PLC0415` on a function-level import of an optional extra.
- **Never used:** a `# type: ignore` or `# ty: ignore` without a rule code and a reason (the code
  writes `# ty: ignore[rule] - reason`, or puts the reason in a comment directly above), a bare `# noqa`, and `# pragma: no cover` outside the
  patterns in `[tool.coverage.report] exclude_also`.

## Typing

- **Modern syntax only** (Python 3.12+): `list[str]`, `X | None`, `type Clock = Callable[[], datetime]`,
  PEP 695 generics, `typing.Self`.
- **`@override`** marks every method that overrides a method of a class it inherits from. Classes
  that satisfy a protocol structurally, such as the adapters, inherit nothing, so their methods
  carry no `@override` (ty would report it).
- **Closed sets** are `Literal` or `enum.StrEnum`, for example `SetupMode`, `KeyMode` and `Format`.
- **Interfaces are `typing.Protocol`s.** Implementations don't inherit from them: the adapters
  satisfy `Adapter` structurally, and `Prompter` and `AdapterFactory` work the same way.
- **No `Any` in public signatures.** Parsed JSON or TOML is narrowed and validated right away.
- **Every annotation counts,** in tests and fixtures too, including `-> None`.

## Value objects

Data that crosses a function boundary is a frozen, slotted, keyword-only dataclass that validates
itself:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class StoreInfo:
    name: str
    encrypted: bool
    ...

    def __post_init__(self) -> None:
        validate_store_name(self.name)
        ...
```

- **Collections inside are immutable:** `tuple`, `frozenset`, or a `MappingProxyType` over a copy.
  For a field set in `__post_init__`, use `object.__setattr__`.
- **Secret-bearing fields use `field(repr=False)`,** or the class defines a redacting `__repr__`
  (as `KeyMaterial` and `Passphrase` do).
- **Prefer named constructors** over a long argument list when an object has distinct forms:
  `StoreRecord.plain(...)` and `StoreRecord.sealed(...)`.

## Structure

- **Pure core, I/O at the edges.** Validation, merging, serialization and crypto are pure. Adapters
  and frontends do the I/O.
- **Size limits.** Small functions with one job. Keep modules under about 400 lines and functions
  under about 40.
  - Some modules are already near or above the module limit, for example `library/store.py` and
    `service.py` (check with `wc -l`).
  - Don't grow them further. Split helpers out, as `adapters/postgres/` does with `url.py`,
    `rows.py`, `schema.py` and `read_only.py`.
- **Dependencies come in as parameters:** clock, KDF parameter factory, adapter opener, prompter,
  environment, stdin reader. There are no module-level singletons and no mutable globals.
- **Public modules define `__all__`.** Private helpers start with `_`.
- **Resources use context managers:** files, locks, connections, stores. Adapters and
  `EnvironmentStore` implement `close()`, `__enter__` and `__exit__`.
- **`pathlib.Path` for paths.** Timestamps are timezone-aware UTC.

## Errors

Raise the most specific subclass of `EnvironmentStoreError`, and build the message first:

```python
if not STORE_NAME_PATTERN.fullmatch(name):
    message = (
        f"invalid store name {name!r}: use 1 to 63 lowercase letters, digits, '_' or '-', "
        f"starting with a letter ({STORE_NAME_PATTERN.pattern})"
    )
    raise ValidationError(message)
```

- **A message says what failed and how to fix it.** A remedy that names a library parameter goes
  into `hint=`, so the CLI and TUI can replace it with their own flag or key.
- **Chain with `raise ... from err`.** The exception: when the original error could carry secret
  data (a decode error over a key, a passphrase or a ciphertext), use `from None`.
- **No broad `except`.** Never a bare `except:`. Never `except Exception:` without re-raising,
  except in shell completion, which must never fail visibly.
  Wrap driver and OS errors into `BackendError` at the adapter boundary.
- **The library never calls `print`, `sys.exit` or `input`.** Only `cli/` and `tui/` talk to the
  terminal.
- **Warnings.** The library reports non-fatal problems with `warnings.warn(...)`, for example
  `CredentialsInProjectFileWarning`. pytest turns every warning into an error, so a test
  that triggers one needs `pytest.warns`.
- **Logging.** If you add logging, use `logging.getLogger(__name__)` and never add handlers in the
  library.

## Secrets

These rules are reviewed as strictly as failing tests:

- **No secret in an error message, a `repr` or a log line.** That covers keys, passphrases and
  decrypted values. Validation errors name the store or the variable, never the value.
- **Randomness for keys, nonces and salts** comes from `secrets` or `os.urandom` only.
- **Key and output files** are created with mode `0600`, and key files with `O_CREAT | O_EXCL`.
- **SQL uses parameters only.** Values always go in as parameters. The only identifier that comes
  from input, the PostgreSQL schema name, is validated and always passed as
  `psycopg.sql.Identifier`. Fixed table and column names may stand in the `psycopg.sql.SQL`
  template.
- **Forbidden:** `eval`, `exec`, `pickle`, `shell=True` and `yaml.load`.
- **Connection strings may hold passwords.** Show a location without credentials
  (`connection_location`) and never the URL itself.
- **Prove it with a test.** Tests show that a secret is absent from the message and the `repr`.
  For examples, see `tests/unit/config/test_secrets.py::test_wrong_secret_text_never_appears_in_the_error`
  and `tests/unit/config/test_secrets.py::test_new_secret_hides_the_secret_in_its_repr`.

## Comments and docstrings

- **Google-style docstrings** with `Args:`, `Returns:`, `Raises:` and `Attributes:`.
- **CLI callbacks are the exception.** Typer prints a callback's whole docstring as its `--help`
  text, and the first line is the summary in `envs --help`. So a callback's docstring is written for
  users and has no `Args:` or `Returns:` sections. Parameters are documented with the `help=` of
  their options.
- **Comments explain why, in place.** For example:
  `# fullmatch: $ alone would also accept a trailing newline.`
- **Never point at an external document,** an issue or a plan ("see spec §4"). The reason has to
  stand on its own.

## Commits and changelog

- **Small commits,** each with an imperative subject (`Add the YAML file serializer`) and a body
  that says why.
- **User-visible changes** go under `## [Unreleased]` in `CHANGELOG.md`, in Keep a Changelog
  sections (`### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Security`).
- **Never commit** key files, `.env` files or coverage output. `.gitignore` covers `.env` and the
  coverage files, but has no pattern for key files, so check `git status` before you commit.
