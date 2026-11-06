# Environment Store V2 — Implementation plan

Companion to [SPEC-V2.md](SPEC-V2.md) (what to build) and [CONTRIBUTING.md](CONTRIBUTING.md) (binding engineering
rules). This document fixes **build order, module layout and the interfaces between work packages**, so that later
packages — especially the adapters, which are built in parallel — can rely on them without touching shared files.

Work happens on the branch `feature/v2`. Each work package (WP) maps to an item in the
[Environment Store V2 project](https://github.com/users/mkaufhol/projects/2).

Revision 2: incorporates the adversarial plan review (setup mode for migrations, key mode lookup, store name
validation everywhere, codec row types, import direction, contract backend factory, backend error category,
dotenv compatibility, CI triggers and service container).

## 1. Phases

| Phase | Work packages | Mode | Gate before the next phase |
|---|---|---|---|
| 0 | Rules and plan (this file, CONTRIBUTING.md) | — | adversarially reviewed |
| 1 · Base | B1 skeleton → B2 domain → B3 merge → B4 contract → B5 crypto + service → B6 SQL common | **sequential**, one commit per WP | full definition of done green, independent review findings fixed |
| 2 · Adapters | A1 files · A2 SQLite · A3 PostgreSQL · A4 formats | **parallel**, one git worktree + branch per WP | each branch green on its own; merged into `feature/v2`; full suite green after the merge; review findings fixed |
| 3 · Frontends | L1 library + project file → C1 CLI foundation → C2–C4 CLI commands (parallel) → T1 TUI | mixed | same |
| 4 · Release | D1 docs, skill, changelog, release workflow | sequential | 2.0.0 |

Mapping to the project items: B1 = 01, B2 = 02, B3 = 03, B4 = 04, B5 = 05, B6 = shared part of 07/08, A1 = 06,
A2 = 07, A3 = 08, A4 = 09, L1 = 10, C1 = 11, C2 = 12, C3 = 13, C4 = 14, T1 = 15, D1 = 16.

Phase 3 and 4 are planned here at module level; their detailed interfaces are fixed at the end of phase 2.

## 2. Validation (applies to every WP)

1. **TDD** as defined in CONTRIBUTING.md §2.
2. **Definition of done** (CONTRIBUTING.md §1): `ruff format --check`, `ruff check`, `ty check --error-on-warning`,
   `bandit`, `pytest` with 100 % line + branch coverage.
3. **Independent review** by reviewers that did not write the code, each with one lens:
   - *spec conformance* — every spec rule and decision (D-number) the WP covers is implemented and tested;
   - *engineering rules* — CONTRIBUTING.md (typing, design, errors, tests that test behaviour);
   - *security* — for WPs touching keys, crypto, SQL, files or subprocesses.
   Findings are verified, fixed test-first, and the gates are re-run.
4. Parallel WPs additionally pass the **full suite after merging** into `feature/v2`.

## 3. Package layout and import direction

```text
src/environment_store/
├── __init__.py              # __version__; public API grows in L1
├── py.typed
├── _toml.py                 # B1: minimal TOML writer (stdlib can only read TOML)
├── core/                    # pure domain, imports nothing outside core/ (except stdlib)
│   ├── __init__.py          # re-exports of core only
│   ├── errors.py            # B2: exception hierarchy
│   ├── validation.py        # B2: store / variable name and value rules
│   ├── secrets.py           # B2: KeyMaterial, Passphrase, Secret (redacted repr)
│   ├── models.py            # B2: StoreInfo, StoreRecord, CipherMeta, KdfParams, Source, …
│   ├── clock.py             # B2: Clock type, utc_now()
│   ├── merge.py             # B3: merge order, merge(), nested keys, bool settings
│   ├── adapter.py           # B4: Adapter / MigratableAdapter protocols, SetupMode
│   └── connection.py        # B4: scheme registry, open_adapter()
├── crypto/                  # B5: imports core only
│   ├── __init__.py
│   ├── keyfile.py           # key file format, generate / read / write (0600, O_EXCL)
│   ├── kdf.py               # Argon2id
│   └── aead.py              # payload + AAD encoding, AES-256-GCM seal / open
├── service.py               # B5: StoreService — imports core + crypto
├── adapters/                # import core (+ adapters/sql), never service or crypto
│   ├── __init__.py
│   ├── sql/                 # B6: shared by SQLite and PostgreSQL
│   ├── files/               # A1
│   ├── sqlite/              # A2
│   └── postgres/            # A3
├── formats/                 # A4: imports core only
├── config/                  # L1
├── cli/                     # C1–C4
└── tui/                     # T1
tests/
├── conftest.py              # Hypothesis profiles (B1)
├── support/                 # B2/B4: strategies, in-memory fake adapter, fake clock
├── contract/                # B4: adapter contract suite (a reusable test class)
├── unit/<mirrors src>/      # unit tests per module
└── adapters/<name>/         # A1–A3: adapter tests (contract subclass + backend specifics)
```

- **Import direction:** `core` ← `crypto` ← `service`; `core` ← `adapters`; `core` ← `formats`. No module imports
  "upwards". A smoke test imports every subpackage first in a fresh interpreter (`python -c "import …"` per
  package) to catch cycles.
- **Ownership rule for parallel phases:** a parallel WP only creates or edits files inside its own directories
  (`src/environment_store/<its package>/`, `tests/adapters/<its name>/` or `tests/unit/<its package>/`). Shared
  files (`pyproject.toml`, `uv.lock`, CI, `core/`, `adapters/sql/`, `tests/conftest.py`, `tests/support/`,
  `tests/contract/`) are prepared in phase 1. If a parallel WP finds a defect in a shared file, it reports it
  instead of editing it.

## 4. Phase 1 — Base

### B1 · Project skeleton (item 01)

- Delete all V1 code, tests, docs (keep `docs/assets/`), `tox.ini` and the V1 agent skill
  (`.claude/skills/environment-store-cli/`). Replace `README.md` with a short V2 placeholder linking to the spec.
  Add an `Unreleased — 2.0.0` section to `CHANGELOG.md`.
- `pyproject.toml`:
  - `version = "2.0.0.dev0"`, `requires-python = ">=3.13"`, classifiers 3.13–3.15, keywords updated; build
    backend `uv_build` pinned to the range matching the installed uv.
  - `dependencies = ["cryptography>=44"]` (D6, D34).
  - extras: `postgres = ["psycopg[binary]>=3.2"]`, `cli = ["typer>=0.15"]`, `tui = ["textual>=3"]`,
    `all = [...]`. Entry points `environment-store` and `envs` are added in C1, not now.
  - dependency groups: `dev` (ruff, ty, pre-commit, bandit), `testing` (pytest, coverage, hypothesis,
    `psycopg[binary]`, `typer`, `textual`, `python-dotenv` — the last one only for dotenv compatibility tests).
    Default groups: both. So `uv sync` gives ty and pytest every optional import.
  - ruff: `target-version = "py313"`, `line-length = 100`, a strict rule selection including at least
    `E W F I N UP B A C4 SIM RET PTH PL RUF ANN S PT TID TC ERA PERF FBT EM TRY D`,
    `pydocstyle.convention = "google"`, `flake8-tidy-imports.ban-relative-imports = "all"`; tests may ignore
    `S101`, `D`, `PLR2004`. No other blanket ignores without a comment.
  - ty: `python-version = "3.13"`; CI and pre-commit run `ty check --error-on-warning`.
  - pytest: `addopts = "-ra --strict-markers --strict-config"`, `xfail_strict = true`,
    `filterwarnings = ["error"]`, `testpaths = ["tests"]`, marker `postgres`.
  - coverage: `branch = true`, `source = ["environment_store"]`, `fail_under = 100`, `show_missing = true`,
    `exclude_also` for `if TYPE_CHECKING:`, `\.\.\.$` protocol bodies, `raise NotImplementedError`,
    `if sys.platform == "win32":`.
  - bandit: `exclude_dirs = ["tests"]`.
- `tests/conftest.py`: Hypothesis profiles `default` (`deadline=None`, which adapter tests need) and `ci`
  (`deadline=None`, fixed `max_examples`, `derandomize=True`), selected via `HYPOTHESIS_PROFILE`.
- `.pre-commit-config.yaml`: current hook versions; ruff check + format, uv-lock, ty (`--error-on-warning`),
  bandit with `-c pyproject.toml -r src`.
- CI (`.github/workflows/ci.yml`): triggers on push to `main`, `feature/**`, `v2/**` and on pull requests. Lint job
  (format check, ruff, ty, bandit); test matrix 3.13 / 3.14 / 3.15 with a `services: postgres` container and
  `ENV_STORE_TEST_POSTGRES_URL` pointing at it, `HYPOTHESIS_PROFILE=ci`, `uv run --python X coverage run -m pytest`
  + `coverage report`; build job. `release.yml` stays as is. Windows is not tested in V2.0 (the `msvcrt` branch of
  A1 is documented as unverified).
- `src/environment_store/__init__.py` (`__version__` via `importlib.metadata`), `py.typed`.
- `_toml.py`: `dumps(document: Mapping[str, TomlValue]) -> str` for the subset V2 needs: `str`, `int`, `bool`,
  aware `datetime`; nested mappings at top level become `[table]`s, deeper mappings inline tables; keys bare when
  they match `[A-Za-z0-9_-]+`, quoted otherwise; strings as basic strings with full TOML escaping. Property test:
  `tomllib.loads(dumps(x)) == x` for generated documents.
- A smoke test for `__version__` so the suite is green at 100 %.

### B2 · Domain model and validation (item 02)

- `core/errors.py` — every class derives from `EnvironmentStoreError`; the category classes are what C1 maps to
  exit codes (D24):

  | Category (exit code) | Parent | Concrete errors |
  |---|---|---|
  | `EnvironmentStoreError` (1) | `Exception` | root |
  | `ValidationError` (1) | root, `ValueError` | invalid names, values, URLs, arguments; `AlreadyEncryptedError`, `NotEncryptedError` (also: a secret given for a plaintext store), `PlaintextNotAllowedError` |
  | `ConfigurationError` (1) | root | no connection configured (D29), bad env values, project file problems |
  | `MissingExtraError` (1) | root | optional dependency not installed (`extra: str`) |
  | `BackendError` (1) | root | every OS / driver / I/O failure of a backend, chained `from err`, message names the location but never credentials; lock and serialization timeouts; `UnsupportedFormatError` (unknown file format, cipher, mode or KDF, or out-of-bounds KDF parameters), `DatabaseNotCleanError`, `SchemaOutdatedError`, `SchemaTooNewError`, `SetupPrivilegeError` |
  | `NotFoundError` (2) | root | `StoreNotFoundError`, `VariableNotFoundError` (`names: tuple[str, ...]`) |
  | `AlreadyExistsError` (3) | root | `StoreExistsError`, `VariableExistsError` (`names: tuple[str, ...]`) |
  | `CryptoError` (4) | root | `KeyRequiredError`, `DecryptionError`, `InvalidKeyFileError`, `KeyModeMismatchError` |
  | `ConcurrentModificationError` (5) | root | — |

- `core/validation.py`: `validate_store_name` (D27 regex), `validate_variable_name` (`^[A-Za-z_][A-Za-z0-9_]*$`),
  `validate_value` (any `str` without `\x00`, D28), `validate_variables(Mapping[str, str])`. Each raises
  `ValidationError` naming the offending item but **never echoing a value** (it may be a secret).
- `core/secrets.py`: `KeyMaterial(key: bytes)` (exactly 32 bytes) and `Passphrase(text: str)` (non-empty), both
  with a redacted `repr`/`str`; `type Secret = KeyMaterial | Passphrase`.
- `core/models.py` (all `frozen=True, slots=True, kw_only=True`):
  - `Cipher(StrEnum)`: `AES256GCM = "aes256gcm"`; `KeyMode(StrEnum)`: `KEYFILE`, `PASSPHRASE`.
  - `KdfParams`: `name: Literal["argon2id"]`, `iterations: int = 3`, `memory_kib: int = 65536`, `lanes: int = 4`,
    `salt: bytes` (16 bytes) (D34); upper bounds enforced on construction (`iterations ≤ 10`,
    `memory_kib ≤ 1048576`, `lanes ≤ 16`) so a tampered store cannot trigger a denial of service;
    `to_json()` / `from_json()` with the spec keys `name, t, m, p, salt` (salt base64). Unknown names or invalid
    values → `UnsupportedFormatError`.
  - `CipherMeta`: `cipher: Cipher`, `mode: KeyMode`, `kdf: KdfParams | None` (required iff passphrase);
    `to_json()` / `from_json()` → `{"cipher", "mode", "kdf"?}`; unknown values → `UnsupportedFormatError`.
  - `StoreInfo`: `name`, `encrypted: bool`, `key_mode: KeyMode | None` (None for plaintext stores **and** for
    stores whose mode this version does not recognise), `revision: int`, `created_at`, `updated_at`.
    `list_stores` never fails because of unrecognised cipher metadata.
  - `StoreRecord`: `name` (validated), `revision: int` (≥ 1), `created_at`, `updated_at` (aware,
    `created_at <= updated_at`), and **exactly one** of `variables: Mapping[str, str]` (validated, stored as an
    immutable copy) or `ciphertext: bytes` + `cipher_meta: CipherMeta`. Properties `encrypted`, `info`.
    Constructors `StoreRecord.plain(...)`, `StoreRecord.sealed(...)`. Invariants validated in `__post_init__`.
  - `Source`: `name: str`, `secret: Secret | None` — one entry of a load list.
  - `PAYLOAD_FORMAT_VERSION = 1`.
- `core/clock.py`: `type Clock = Callable[[], datetime]`, `utc_now()`.
- `tests/support/strategies.py`: Hypothesis strategies `store_names()`, `invalid_store_names()` (incl. `../x`,
  `a/b`, `A`, empty), `variable_names()`, `values()` (incl. empty, multi-line, unicode, quotes, `$`, `=`, `'`,
  leading/trailing whitespace; never NUL), `variable_maps()`, `plain_records()`, `sealed_records()`.
  `tests/support/clock.py`: deterministic fake clock.

### B3 · Merge logic (item 03)

- `core/merge.py`:
  - `MergeOrder(StrEnum)`: `LAST_WINS`, `FIRST_WINS`.
  - `merge(stores: Sequence[tuple[str, Mapping[str, str]]], *, order: MergeOrder = LAST_WINS) -> dict[str, str]`.
  - `merge_with_sources(...) -> dict[str, tuple[str, str]]` (value + winning store, for `ls --source`).
  - `nested(stores) -> dict[str, dict[str, str]]` (store → variables, for JSON/TOML `--nested`).
  - `nested_flat_key(store: str, variable: str) -> str` → store name in SCREAMING_SNAKE_CASE (`-` → `_`), `__`,
    then the variable name unchanged (D30); `nested_flat(stores) -> dict[str, str]` raising `ValidationError` on a
    collision.
  - `parse_bool_setting(raw: str, *, setting: str) -> bool` (`true/false/1/0/yes/no`, case-insensitive; anything
    else raises `ConfigurationError`).
  - `order_from_setting(*, ordered_overwrite: bool) -> MergeOrder`.

### B4 · Adapter contract, connection registry, contract suite (item 04)

- `core/adapter.py`:

  ```text
  class SetupMode(StrEnum): AUTO, NONE

  class Adapter(Protocol):
      list_stores() -> list[StoreInfo]                       # sorted by name
      create_store(record: StoreRecord) -> None              # record.revision must be 1 (else ValidationError);
                                                             # StoreExistsError; atomic: two racing creates →
                                                             # exactly one wins
      read_store(name: str) -> StoreRecord                   # StoreNotFoundError
      write_store(record: StoreRecord, *, expected_revision: int) -> None
          # stored revision == expected_revision, else ConcurrentModificationError and nothing written (D7);
          # record.revision == expected_revision + 1, else ValidationError; StoreNotFoundError
      delete_store(name: str) -> None                        # StoreNotFoundError
      close() -> None;  __enter__() -> Self;  __exit__(*exc) -> None

  class MigratableAdapter(Adapter, Protocol):
      migrate() -> MigrationReport                           # SQL adapters only (D11)
  ```

  - Every method validates store names (defense in depth; the service validates first).
  - Every backend, OS or driver failure is raised as `BackendError` (chained), never raw.
  - `SetupMode.AUTO` (default): SQL adapters inspect and set up the database on open (D11/D13).
    `SetupMode.NONE`: open does not inspect; `migrate()` creates (EMPTY) or upgrades (OUTDATED), is a no-op on
    CURRENT and raises on FOREIGN / NEWER; any data operation first runs the AUTO check lazily. File adapters
    accept and ignore the mode. This is how the `migrate` command and an admin's first setup reach `migrate()`.
  - `MigrationReport`: `from_version: int | None`, `to_version: int`, `created: bool`.
- `core/connection.py`:
  - `scheme_of(url: str) -> str` (lowercased; `ValidationError` for strings without `scheme://`).
  - `AdapterEntry(target: str, extra: str | None, requires: tuple[str, ...])` and
    `ADAPTER_FACTORIES: Mapping[str, AdapterEntry]`, **pre-registered for all V2 schemes** so parallel adapter
    WPs never edit this file: `json` → `environment_store.adapters.files:open_json`, `toml` →
    `environment_store.adapters.files:open_toml`, `sqlite` → `environment_store.adapters.sqlite:open_sqlite`,
    `postgresql` / `postgres` → `environment_store.adapters.postgres:open_postgres` (`extra="postgres"`,
    `requires=("psycopg",)`). Every factory has the signature
    `(url: str, *, setup: SetupMode = SetupMode.AUTO) -> Adapter` and parses its own URL.
  - `open_adapter(url, *, setup=SetupMode.AUTO, factories=ADAPTER_FACTORIES) -> Adapter` — unknown scheme →
    `ValidationError` listing the supported schemes; only a `ModuleNotFoundError` whose `.name` top-level package
    is in the entry's `requires` becomes `MissingExtraError(entry.extra)`; any other import error propagates
    unchanged (tested). Adapters import their optional dependencies at module level and never raise
    `MissingExtraError` themselves.
- `tests/support/memory_adapter.py`: `MemoryAdapter` + `MemoryBackend`, an in-memory reference implementation
  (used by core tests and as the contract suite's own reference).
- `tests/contract/adapter_contract.py`: `class AdapterContract` with one abstract fixture, `make_backend`, that
  returns a `Callable[[], ContextManager[Backend]]`. A `Backend` is a fresh, empty, isolated backend with
  `open(*, setup=SetupMode.AUTO) -> Adapter` (each call opens a **new** adapter instance on the same backend; used
  for persistence and race tests); leaving the context cleans it up. Hypothesis tests create one backend per
  example. Each adapter test module subclasses the contract and implements only `make_backend`. The suite covers:
  empty listing; create / read round-trip for plain and sealed records (Hypothesis: arbitrary names, values and
  binary ciphertexts); duplicate create; racing creates; listing sorted with correct `StoreInfo` (incl.
  `key_mode`); write with correct revision; stale revision → `ConcurrentModificationError` and nothing written;
  wrong record revision; write / read / delete of a missing store; invalid store names rejected by every method;
  delete then re-create; persistence across `open()`; two instances racing on the same revision → exactly one wins;
  timestamps preserved (aware UTC, microsecond precision); context manager closes.
- `MemoryAdapter` passes `AdapterContract`.

### B5 · Encryption and store service (item 05)

- `crypto/keyfile.py`: format `envstore-key-v1:<urlsafe base64 of 32 bytes, no padding>` + `\n`;
  `generate_key() -> KeyMaterial` (`secrets.token_bytes`), `format_key`, `parse_key(text) -> KeyMaterial`
  (`InvalidKeyFileError`), `looks_like_key_file(text) -> bool`, `read_key_file(path)`,
  `write_key_file(path, key)` (`O_CREAT | O_EXCL`, mode `0600`, refuses to overwrite → `ValidationError`),
  `read_passphrase_file(path)` (strips one trailing newline, D3).
- `crypto/kdf.py`: `new_kdf_params() -> KdfParams` (random salt, D34 defaults), `derive_key(passphrase, params) ->
  KeyMaterial` via `cryptography`'s Argon2id.
- `crypto/aead.py`:
  - plaintext payload = canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, UTF-8) of
    `{"variables": {...}}`;
  - AAD = canonical JSON of `{"store": name, "format": PAYLOAD_FORMAT_VERSION, "cipher": meta.to_json()}` (D5);
  - `seal(variables, *, store, meta, key) -> bytes` → `nonce (12 random bytes) || AESGCM ciphertext+tag`;
  - `open_sealed(ciphertext, *, store, meta, key) -> dict[str, str]` → `DecryptionError` on any failure (wrong
    key, tampering, other store name, changed metadata, malformed payload), never leaking details.
- `service.py` — `StoreService(adapter, *, clock=utc_now, kdf_params_factory=new_kdf_params)`; the single
  implementation of all operations used by L1 and the CLI:
  - **every** method validates every store name it receives (incl. `copy` / `move` source and destination and every
    `Source` in `load`) before touching the adapter; parametrised tests per method with invalid names;
  - `list_stores()`, `create_store(name, *, secret: Secret | None = None) -> StoreInfo`, `delete_store(name)`;
  - `parse_secret(name, text: str) -> Secret` — interprets raw `-k` file / stdin / prompt text by the store's
    mode (D3): keyfile store → `parse_key` (`InvalidKeyFileError` if it is not a key file); passphrase store →
    `Passphrase`, but text that looks like a key file → `KeyModeMismatchError`; plaintext store →
    `NotEncryptedError`;
  - `read_variables(name, *, secret=None) -> dict[str, str]`;
  - `set_variables(name, values, *, secret=None, overwrite=False)` — conflicts → `VariableExistsError` listing
    all conflicting names, nothing written (D18);
  - `delete_variables(name, names, *, secret=None)` — missing → `VariableNotFoundError` listing them, nothing
    written;
  - `encrypt_store(name, *, secret)` (D4; `AlreadyEncryptedError`), `rekey_store(name, *, old, new)` (new salt,
    may switch mode; `NotEncryptedError`);
  - `copy_store(src, dst, *, secret=None, encryption: Literal["same", "plain"] | Secret = "same",
    destination: StoreService | None = None)` and `move_store(...)` (copy, then delete the source; a failure never
    leaves zero copies) — re-encrypts because of D5; `dst` existing → `StoreExistsError`;
  - `load(sources: Sequence[Source]) -> list[tuple[str, dict[str, str]]]` in source order.
  - Encrypted store without a secret → `KeyRequiredError`; secret for a plaintext store → `NotEncryptedError`;
    secret type not matching the store's mode → `KeyModeMismatchError` — in read, set, delete and load alike.
  - Every write is read → modify → seal with a fresh nonce → `write_store(..., expected_revision=...)` with
    `updated_at = clock()`.
- Argon2id is slow by design: tests inject cheap `KdfParams` through `kdf_params_factory`, and exactly one test
  asserts the spec defaults.

### B6 · SQL common (shared part of items 07/08)

- `adapters/sql/schema.py`: `SCHEMA_VERSION = 1`, `META_APP = "environment-store"`; DDL v1 (D12) as statement
  tuples: `SQLITE_SCHEMA_V1` and `POSTGRES_SCHEMA_V1` (the latter with a `{schema}` placeholder that A3 composes
  with `psycopg.sql.Identifier`); including the `meta` rows.
- `adapters/sql/migrations.py`: `Migration(version: int, statements: tuple[str, ...])`, `SQLITE_MIGRATIONS`,
  `POSTGRES_MIGRATIONS` (same `{schema}` placeholder), `pending(migrations, current: int | None) ->
  list[Migration]`. Applying a migration also updates `meta.schema_version` in the same transaction.
- `adapters/sql/setup.py` (pure, D11/D13): `DatabaseInspection(tables: frozenset[str], meta: Mapping[str, str] |
  None)`; `SetupState(StrEnum)`: `EMPTY`, `CURRENT`, `OUTDATED`, `NEWER`, `FOREIGN` (tables without a valid
  `meta`, a `meta` with another `app`, or a non-integer version); `classify(inspection) -> SetupState`;
  `SetupAction(StrEnum)`: `CREATE`, `USE`, `UPGRADE`; `decide(state, *, auto_upgrade: bool) -> SetupAction`
  raising `DatabaseNotCleanError` (FOREIGN), `SchemaTooNewError` (NEWER) and `SchemaOutdatedError` (OUTDATED
  without auto-upgrade, hint: run `environment-store migrate`).
- `adapters/sql/codec.py`: `Dialect(StrEnum)`: `SQLITE`, `POSTGRES`; `StoreRow` (frozen dataclass with the eight
  `stores` columns in DDL order: `name, encrypted, cipher_meta, variables, ciphertext, revision, created_at,
  updated_at`); `record_to_row(record, *, dialect) -> StoreRow` and `row_to_record(row, *, dialect) ->
  StoreRecord`; `row_to_info(...)` that never fails on unrecognised cipher metadata. Per dialect:

  | Column | SQLite value | PostgreSQL value |
  |---|---|---|
  | `encrypted` | `int` 0/1 | `bool` |
  | `variables`, `cipher_meta` | JSON `str` | `dict` (A3 wraps it in `psycopg.types.json.Jsonb`) |
  | `ciphertext` | `bytes` | `bytes` |
  | timestamps | ISO 8601 UTC `str` with microseconds | aware `datetime` |

## 5. Phase 2 — Adapters and formats (parallel)

Each WP runs in its own worktree on branch `v2/<wp>` created from `feature/v2` after phase 1, and only touches its
own directories (§3).

### A1 · JSON and TOML file adapters (item 06)

`adapters/files/`: `open_json(url, *, setup)`, `open_toml(url, *, setup)`, one `FileAdapter` parameterised by a
`FileSerializer` (serializer pair). URL → directory (`json://rel`, `json:///abs`, `json://~/dir`); directory
created on first write. One file per store, store name = file stem; files with other extensions **or stems that
violate D27** are ignored (tested). File layout per spec §3.2 (`format`, `encrypted`, `revision`, `created_at`,
`updated_at`, `variables` | `payload` + `[cipher]`). Create and write under a per-store lock (`fcntl.flock` on
POSIX; `msvcrt.locking` behind `sys.platform == "win32"`, unverified in V2.0); create uses `O_EXCL` semantics so
two racing creates cannot both succeed; revision check under the lock; temp file in the same directory,
`os.replace`. TOML via `tomllib` + `environment_store._toml.dumps`. Corrupt or foreign files → `BackendError`
naming the file; unknown `format` → `UnsupportedFormatError`. Tests: contract suite for both formats, layout
golden files, atomicity (temp files cleaned up on failure), concurrent writers via two processes.

### A2 · SQLite adapter (item 07)

`adapters/sqlite/`: `open_sqlite(url, *, setup)` (`sqlite:///relative.db`, `sqlite:////absolute.db`); stdlib
`sqlite3`, `journal_mode=WAL`, `busy_timeout`. With `SetupMode.AUTO`: inspect (`sqlite_master`, `meta`) →
`classify` → `decide(auto_upgrade=True)` → create / upgrade / use; refused states raise the B6 errors and change
nothing. `write_store` as one `UPDATE … WHERE name = ? AND revision = ?` (0 rows → conflict or not found).
`migrate()` implemented. `sqlite3` errors → `BackendError`. Tests: contract suite, every setup state, check
constraint enforcement, two connections racing.

### A3 · PostgreSQL adapter (item 08)

`adapters/postgres/`: `open_postgres(url, *, setup)`; `?schema=` (default `environment_store`, regex
`^[a-z_][a-z0-9_]{0,62}$`) removed from the URL before `psycopg.connect`. With `SetupMode.AUTO`: inspect the schema
→ `classify` → `decide(auto_upgrade=False)`; empty → `CREATE SCHEMA` + v1 in one transaction; missing privilege →
`SetupPrivilegeError` with the `migrate` hint. With `SetupMode.NONE`, `migrate()` creates or upgrades. All SQL
composed with `psycopg.sql`; JSONB / BYTEA / TIMESTAMPTZ. psycopg errors → `BackendError` (no credentials in
messages). Tests run against a real server: a session fixture uses `ENV_STORE_TEST_POSTGRES_URL` (set in CI by the
service container); locally, if unset, it starts a temporary cluster with `initdb` / `pg_ctl` from `PATH` (unix
socket in a short temp dir, random port, trust auth, `--no-locale`) and stops it afterwards. Each test (and each
Hypothesis example via `make_backend`) gets a fresh database. If neither is available the tests **fail** with a
hint (never skip silently). Tests: contract suite, schema isolation (`?schema=a` vs `?schema=b` in one database),
foreign schema refused, outdated schema refused on AUTO open and upgraded by `migrate()` on a `NONE` open, missing
`CREATE` privilege (a role without it) → hint, identifier injection attempts rejected.

### A4 · Formats (item 09)

`formats/`: `dotenv.dumps(mapping) -> str` and `dotenv.loads(text) -> dict[str, str]`; `json_format` /
`toml_format` `dumps` / `loads` for flat (`dict[str, str]`) and nested (`dict[str, dict[str, str]]`) documents —
`loads` accepts only flat objects of strings (D33); `shell.posix_exports(mapping, *, overwrite: bool) -> str` using
`shlex.quote` and `[ -z "${VAR+x}" ] && export VAR=…` without overwrite (D23); `infer_format(path) -> Format |
None` (D22).

**dotenv compatibility (resolves the review finding on `$`):** python-dotenv only interpolates `${…}` and only
inside unquoted or double-quoted values; Docker Compose interpolates `$VAR` / `${VAR}` in unquoted and
double-quoted values and treats single-quoted values literally. The writer therefore uses:

1. unquoted for values made only of `[A-Za-z0-9_./:@%+,-]` (non-empty);
2. **single quotes** for single-line values that contain no `'` — literal in both tools, so `$` needs no escape;
3. **double quotes** with `\\`, `\"`, `\n`, `\r`, `\t` escapes for values with newlines or `'`, as long as they
   contain no `$`;
4. a value that needs double quotes **and** contains `$` cannot be written so that both tools read it back exactly
   → `ValidationError` naming the variable and recommending `-t json`, `-t toml` or `envs run`.

The exact rules are verified with golden tests against python-dotenv (testing dependency) and documented Compose
semantics; if the measured behaviour differs from the above, stop and report before choosing another rule. Property
tests: `loads(dumps(x)) == x` for every format and every representable value; shell output evaluated by
`/bin/sh -c` in a test reproduces the values exactly.

## 6. Phase 3 and 4 — outline

- **L1 · Library and project file (item 10):** `config/` — `.envstore.toml` discovery (cwd upwards), schema
  validation, precedence resolution (CLI > env > project file > default) for connection and merge order, password
  warning (D25); secret sources (file, stdin, prompt via an injected `Prompter`, `--noinput`) turned into
  `Secret`s with `StoreService.parse_secret`. Public API in `environment_store/__init__.py`: `EnvironmentStore`,
  `Source`, `load(*stores)` (D36), errors.
- **C1 · CLI foundation (item 11):** typer app, entry points `environment-store` and `envs`, global options,
  positional store lists with `-k store=path`, exit-code mapping from the error categories, `--json`; the
  `migrate` command opens with `SetupMode.NONE`.
- **C2–C4 (items 12–14):** command groups, built in parallel once C1 is merged (one module per group).
- **T1 · TUI (item 15)**, **D1 · docs and release (item 16)**.
