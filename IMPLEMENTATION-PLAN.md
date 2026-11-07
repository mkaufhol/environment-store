# Environment Store V2 — Implementation plan

Companion to [SPEC-V2.md](SPEC-V2.md) (what to build) and [CONTRIBUTING.md](CONTRIBUTING.md) (binding engineering
rules). This document fixes **build order, module layout and the interfaces between work packages**, so that later
packages — especially the adapters, which are built in parallel — can rely on them without touching shared files.

Work happens on the branch `feature/v2`. Each work package (WP) maps to an item in the
[Environment Store V2 project](https://github.com/users/mkaufhol/projects/2).

Revision 2: incorporates the adversarial plan review (setup mode for migrations, key mode lookup, store name
validation everywhere, codec row types, import direction, contract backend factory, backend error category,
dotenv compatibility, CI triggers and service container).

Revision 3: detailed phase 3 plan (§6) with plan decisions PD 1–30 (§6.4); phase 4 outline moved to §7.

## 1. Phases

| Phase | Work packages | Mode | Gate before the next phase |
|---|---|---|---|
| 0 | Rules and plan (this file, CONTRIBUTING.md) | — | adversarially reviewed |
| 1 · Base | B1 skeleton → B2 domain → B3 merge → B4 contract → B5 crypto + service → B6 SQL common | **sequential**, one commit per WP | full definition of done green, independent review findings fixed |
| 2 · Adapters | A1 files · A2 SQLite · A3 PostgreSQL · A4 formats | **parallel**, one git worktree + branch per WP | each branch green on its own; merged into `feature/v2`; full suite green after the merge; review findings fixed |
| 3 · Frontends | L1 library + project file → C1 CLI foundation → C2–C4 CLI commands (parallel) → T1 TUI | mixed (§6.1) | same |
| 4 · Release | D1 docs, skill, changelog, release workflow | sequential | 2.0.0 |

Mapping to the project items: B1 = 01, B2 = 02, B3 = 03, B4 = 04, B5 = 05, B6 = shared part of 07/08, A1 = 06,
A2 = 07, A3 = 08, A4 = 09, L1 = 10, C1 = 11, C2 = 12, C3 = 13, C4 = 14, T1 = 15, D1 = 16.

Phase 3 is planned in detail in §6 (fixed at the end of phase 2, against the merged code); phase 4 is an outline
(§7).

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
├── config/                  # L1 (detailed in §6.1)
├── library/                 # L1
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
`shlex.quote` and `[ -n "${VAR+x}" ] || export VAR=…` without overwrite (D23); `infer_format(path) -> Format |
None` (D22).

**dotenv compatibility (resolves the review finding on `$`):** python-dotenv interpolates `${…}` in every quoting
style (measured with 1.2; single quotes included); Docker Compose interpolates `$VAR` / `${VAR}` in unquoted and
double-quoted values and treats single-quoted values literally. The writer therefore uses:

1. unquoted for values made only of `[A-Za-z0-9_./:@%+,-]` (non-empty);
2. **single quotes** for single-line values without `'`, without `\\` and not ending in `\` (python-dotenv decodes
   `\\` and `\'` inside single quotes);
3. **double quotes** with `\\`, `\"`, `\n`, `\r`, `\t` escapes for all other values, as long as they contain no `$`;
4. refused with `ValidationError` naming the variable and recommending `-t json`, `-t toml` or `envs run`: values that
   need double quotes **and** contain `$`, and values containing `${` (python-dotenv interpolates `${…}` in every
   quoting style, single quotes included — measured in A4, D37 amended accordingly).

The exact rules are verified with golden tests against python-dotenv (testing dependency) and documented Compose
semantics; if the measured behaviour differs from the above, stop and report before choosing another rule. Property
tests: `loads(dumps(x)) == x` for every format and every representable value; shell output evaluated by
`/bin/sh -c` in a test reproduces the values exactly.

## 6. Phase 3 — Frontends

Phase 3 builds the public library on top of `StoreService`, then the CLI in four packages and the TUI. It was
planned against the code as merged after phase 2 (`f4a7eab`) and against the installed toolchain: typer 0.28.0
(click is **vendored** since typer 0.26, there is no separate `click` package), rich 15.0, textual 8.2.8, ty 0.0.98,
ruff 0.17.4. The two typer behaviours the CLI depends on (usage-error exit codes, `--` pass-through for `run`) and
`Annotated` options under `ty check --error-on-warning` and ruff `FBT` were verified with a spike before writing
this section (§6.3).

### 6.1 Order, branches and ownership

| Step | WP | Mode | Branch / worktree | Owns (creates or edits only these) |
|---|---|---|---|---|
| 1 | L1 library + project file | sequential | `feature/v2` | `config/`, `library/`, `environment_store/__init__.py`, `core/errors.py` (one new class, PD 3), `core/connection.py` (one new function, PD 9), `adapters/postgres/url.py` (uses it), `tests/unit/core/`, `tests/adapters/postgres/` (only the URL tests), `tests/support/kdf.py` + `tests/unit/service/conftest.py` (moves `CheapKdf`), `tests/unit/config/`, `tests/unit/library/`, `tests/unit/test_import_direction.py`, `tests/unit/test_package.py` |
| 2 | C1 CLI foundation | sequential | `feature/v2` | `cli/` (all files except the four command packages' bodies), `pyproject.toml` + `uv.lock` (scripts, `cli` and `all` extras), `tests/cli/foundation/`, `tests/cli/conftest.py`, `tests/support/cli.py`, `tests/unit/test_import_direction.py`, `tests/unit/test_extras.py` (new); **creates** the empty command packages and test directories of C2–C4 |
| 3 | C2 store commands | **parallel** | `v2/c2-stores` | `cli/stores/`, `tests/cli/stores/` |
| 3 | C3 variable commands | **parallel** | `v2/c3-variables` | `cli/variables/`, `tests/cli/variables/` |
| 3 | C4 export, run, key commands | **parallel** | `v2/c4-environment` | `cli/exporting/`, `cli/encryption/`, `tests/cli/exporting/`, `tests/cli/encryption/` |
| 4 | T1 TUI | sequential, after C2–C4 are merged | `feature/v2` | `tui/`, `cli/tui_command.py`, one line in `cli/app.py`, `pyproject.toml` + `uv.lock` (`tui` and `all` extras), `tests/tui/`, `tests/cli/test_command_table.py`, `tests/unit/test_import_direction.py` (the `cli.tui_command` exception, PD 31), `tests/unit/test_extras.py` |

- The §3 ownership rule applies to C2–C4. **Everything they share is built in C1**: global options, the CLI state
  object, store-list and `-k` parsing, secret resolution for reading, writing and new secrets, the single stdin
  consumer rule, confirmations, output helpers and `--json`, exit-code mapping, the typer integration classes and
  the test harness. If C2–C4 need something shared that C1 did not provide, they report it; it is added on
  `feature/v2` after the merge (as after phase 2), never in a parallel branch.
- C1 creates each command package with a `register(app: typer.Typer) -> None` function whose body is only its
  docstring, and `cli/app.py` calls all four `register` functions. C2–C4 fill in their own `register`; nobody else
  edits `app.py` until T1. Every command is registered with `cls=EnvsCommand` (or `PassthroughCommand` for
  `run`); C1's `tests/cli/foundation/test_registration.py` walks the real `app` and asserts this for every
  registered command, so it covers C2–C4's commands as soon as they are merged (PD 10).
- After C2–C4 are merged: full definition of done on `feature/v2`, independent reviews (spec conformance,
  engineering rules, security), findings fixed test-first. T1 starts after that.

Updated layout (additions to §3):

```text
src/environment_store/
├── __init__.py              # L1: public API, resolved lazily (PD 1)
├── config/                  # L1: imports core, crypto
│   ├── __init__.py
│   ├── project.py           # .envstore.toml discovery, parsing, schema validation
│   ├── settings.py          # precedence CLI > env > project file > default, password warning
│   ├── secrets.py           # key sources, SecretResolver, new secrets
│   └── prompt.py            # Prompter protocol, GetpassPrompter
├── library/                 # L1: imports core, crypto, service, formats, config
│   ├── __init__.py
│   ├── store.py             # EnvironmentStore (facade over StoreService + adapter)
│   ├── sources.py           # Source, KeyInput
│   ├── environment.py       # Environment (result of load): apply, to_file, dumps
│   ├── files.py             # write_output_file (0600, refuse or atomic replace)
│   ├── keys.py              # generate_key_file, generate_key_text
│   └── oneliner.py          # load(*stores) (D36)
├── cli/                     # C1–C4: imports core, config, library, formats
│   ├── __init__.py          # main() entry point, lazy (no typer import)
│   ├── __main__.py          # python -m environment_store.cli
│   ├── app.py               # build_app(), app, root callback, registration
│   ├── _typer.py            # EnvsGroup, EnvsCommand, PassthroughCommand (only typer-internals touch points)
│   ├── runtime.py           # Runtime: injected terminal / OS boundaries
│   ├── state.py             # CliState: per-invocation settings, store, stdin, interaction
│   ├── options.py           # Annotated option and argument aliases
│   ├── errors.py            # ExitCode, exit_code_for()
│   ├── output.py            # stdout / stderr / JSON / table helpers
│   ├── key_options.py       # -k parsing for reading and writing commands
│   ├── secrets.py           # existing_secret(), new_secret() for commands
│   ├── loading.py           # load_for_reading(): store list + keys + prompts → Environment
│   ├── confirm.py           # require_confirmation()
│   ├── prompts.py           # TerminalPrompter
│   ├── migrate.py           # migrate command
│   ├── stores/              # C2
│   ├── variables/           # C3
│   ├── exporting/           # C4: export, export-shell, run
│   ├── encryption/          # C4: keygen, rekey, encrypt
│   └── tui_command.py       # T1
└── tui/                     # T1: imports core, config, library, formats
tests/
├── support/cli.py           # C1: CliHarness, HookedAdapter, RecordingPrompter, key file helpers
├── unit/config/, unit/library/   # L1
├── cli/                     # C1 (conftest.py, foundation/) and C2–C4 (one directory each)
└── tui/                     # T1
```

Import direction (extended in `tests/unit/test_import_direction.py` by L1, C1 and T1):

| Layer | May import |
|---|---|
| `config` | `core`, `crypto`, `config` |
| `library` | `core`, `crypto`, `service`, `formats`, `config`, `library` |
| `cli` | `core`, `config`, `library`, `formats`, `cli` |
| `tui` | `core`, `config`, `library`, `formats`, `tui` |

Adapters are reached only through `core.connection.open_adapter`; no frontend imports `adapters`, `service` or
`crypto` directly (D31: the frontends use the library). Restricted layers never import the top-level package
`environment_store` (existing rule).

- **One recorded exception (PD 31):** the module `environment_store.cli.tui_command` may import `tui`, and only
  inside its command function (`from environment_store.tui import run_tui  # noqa: PLC0415 - optional extra,
  imported only when "envs tui" runs`). The test encodes it as a per-module table
  `_MODULE_EXCEPTIONS = {"environment_store.cli.tui_command": frozenset({"tui"})}` (added by T1) and asserts that
  no other `cli` module imports `tui` and that no `tui` module imports `cli` (both directions stay forbidden).
- When C1 adds `cli` to `_ALLOWED`, the existing parametrised checker case
  `("environment_store.cli.app", "from environment_store.service import X", 0)` flips to 1; C1 updates it.

### 6.2 Command assignment (spec §6.1)

| Command | WP | Command | WP |
|---|---|---|---|
| `ls-store` | C2 | `import` | C3 |
| `create-store` | C2 | `export` | C4 |
| `rm-store` | C2 | `export-shell` | C4 |
| `cp-store` | C2 | `run` | C4 |
| `mv-store` | C2 | `keygen` | C4 |
| `ls` | C3 | `rekey` | C4 |
| `get` | C3 | `encrypt` | C4 |
| `set` | C3 | `migrate` | C1 |
| `rm` | C3 | `tui` | T1 |

Global options and `--version` are C1. T1 adds `tests/cli/test_command_table.py`, which asserts that `envs --help`
lists exactly the 18 commands of spec §6.1.

### L1 · Library and project file (item 10)

**Covers:** D3 (key sources), D14 (merge-order precedence), D17, D25 (project file), D29 (no default connection),
D31 (library is the facade), D33 (bool values, password warning, project file rules), D35 (`noinput` in the
library one-liner), D36 (one-liner), spec §5, §6.0.3, §7.3.

#### `config/project.py`

```text
PROJECT_FILE_NAME: Final = ".envstore.toml"

@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectFile:
    path: Path                           # absolute
    stores: tuple[str, ...]              # () when absent
    keys: Mapping[str, Path]             # store → absolute path (relative to path.parent, ~ expanded)
    ordered_overwrite: bool | None
    connection: str | None = field(repr=False)   # anchored, see below

@dataclass(frozen=True, slots=True)
class ProjectFileCandidate:
    path: Path
    untrusted_reason: str | None         # None: trusted (PD 32)

find_project_file(start: Path, *, boundary: Path | None = None,
                  uid: int | None = None) -> ProjectFileCandidate | None
untrusted_reason(st_uid: int, st_mode: int, uid: int) -> str | None     # pure, PD 32
read_project_file(path: Path) -> ProjectFile
parse_project_file(text: str, *, path: Path) -> ProjectFile
anchor_connection(url: str, base: Path) -> str
```

- Discovery: `start`, then its parents, first regular file named `.envstore.toml` wins (spec §6.0.3). It stops at
  the filesystem root, or after `boundary` (tests pass their `tmp_path` so a stray file above it never leaks in).
  A directory with that name is skipped.
- Trust check (PD 32): the first file found is used only if it is owned by the current user (`os.geteuid()`) or
  root and is not world-writable (`st_mode & 0o002 == 0`). Otherwise it is **ignored** (the search does not
  continue upwards) and `find_project_file` returns it as untrusted, so `Settings.warnings` names the file and the
  reason ("ignoring project file '/tmp/.envstore.toml': owned by another user"). Signature:
  `find_project_file(start, *, boundary=None, uid: int | None = None) -> ProjectFileCandidate | None` with
  `ProjectFileCandidate(path: Path, untrusted_reason: str | None)`; `uid=None` means `os.geteuid()`, tests pass a
  different uid instead of chowning. On Windows (`if sys.platform == "win32":`, no POSIX owner) the check is
  skipped.
- Schema (strict, PD 6): top-level keys only `stores`, `keys`, `ordered_overwrite`, `connection`; `stores` a list
  of valid store names (D27); `[keys]` a table of valid store names → non-empty strings; `ordered_overwrite` a
  TOML boolean; `connection` a non-empty string. Any violation, unreadable file or TOML syntax error →
  `ConfigurationError` naming the file and the key (never echoing a value). A `[keys]` value that looks like key
  material (`envstore-key-v1:` prefix) is refused: "paths only, never key material" (§6.0.3).
- `anchor_connection` (PD 7): relative `json://`, `toml://` and `sqlite:///` paths in the project file are anchored
  at the file's directory, so `envs` works from any subdirectory; absolute, `~` and other schemes are unchanged.
  Pure string handling, no adapter import.

#### `config/settings.py`

```text
ENV_CONNECTION: Final = "ENV_STORE_CONNECTION"
ENV_ORDERED_OVERWRITE: Final = "ENV_STORE_ORDERED_OVERWRITE"

class ConnectionSource(StrEnum): OPTION, ENVIRONMENT, PROJECT_FILE
class CredentialsInProjectFileWarning(UserWarning)     # emitted by the library one-liner only

@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    connection: str | None = field(repr=False)
    connection_source: ConnectionSource | None
    ordered_overwrite: bool               # resolved env > project file > default (True)
    stores: tuple[str, ...]               # project file default list
    key_paths: Mapping[str, Path]         # project file [keys]
    project_file: Path | None
    warnings: tuple[str, ...]
    def require_connection(self) -> str                  # ConfigurationError (D29)
    def merge_order(self, *, first_wins: bool) -> MergeOrder   # --first-wins > the rest (D14)

resolve_settings(*, connection: str | None, use_project: bool, environ: Mapping[str, str],
                 cwd: Path, boundary: Path | None = None, uid: int | None = None) -> Settings

# core/connection.py (L1 adds; shared with the PostgreSQL adapter)
CREDENTIAL_PARAMETERS: Final[frozenset[str]] = frozenset({"password", "sslpassword"})
connection_has_credentials(url: str) -> bool
```

- Precedence: connection `-c` > `ENV_STORE_CONNECTION` > project file; merge order `--first-wins` >
  `ENV_STORE_ORDERED_OVERWRITE` (parsed with `parse_bool_setting`, D33) > project file > `true`.
- An empty environment variable counts as unset (PD 8). An empty `-c ""` is a `ConfigurationError`.
- D29 message names all three ways: `-c/--connection`, `ENV_STORE_CONNECTION`, `connection` in `.envstore.toml`.
- Password warning (D25/D33): whenever a project file is read and `connection_has_credentials(connection)` is
  true, `warnings` contains the warning recommending `ENV_STORE_CONNECTION`, also when `-c` or the environment
  overrides it (PD 9). The text never contains the password. `--no-project` suppresses it, because the file is not
  read. An ignored untrusted project file (PD 32) adds its own warning and contributes nothing else.
- `connection_has_credentials` (PD 9) lives in `core.connection` so there is one detector: true when the URL
  userinfo has a non-empty password part, or any query parameter whose **percent-decoded** name is in
  `CREDENTIAL_PARAMETERS`. `adapters/postgres/url.py` replaces its private `_CREDENTIAL_PARAMETERS` with the
  core constant (redaction behaviour unchanged, its tests stay green).
- `resolve_settings` reads the project file and parses `ENV_STORE_ORDERED_OVERWRITE` when it is called; a broken
  project file or a bad value raises `ConfigurationError`. *Where* the CLI calls it is fixed in C1
  (`EnvsCommand`, PD 10).

#### `config/prompt.py` and `config/secrets.py`

```text
class Prompter(Protocol):
    def secret(self, prompt: str) -> str: ...            # hidden input
    def new_secret(self, prompt: str) -> str: ...        # hidden, asked twice, must match
    def confirm(self, question: str) -> bool: ...

class GetpassPrompter:      # getpass.getpass on stderr; the library one-liner's prompter (PD 11)

@dataclass(frozen=True, slots=True)
class KeyFile:  path: Path
@dataclass(frozen=True, slots=True)
class KeyStdin: ...
type KeySource = KeyFile | KeyStdin

class StoreInspector(Protocol):                         # implemented by EnvironmentStore
    def store_info(self, name: str) -> StoreInfo: ...
    def parse_secret(self, name: str, text: str) -> Secret: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class SecretInput:
    read_stdin: Callable[[], bytes]     # claims stdin, then reads it (CLI: CliState.read_stdin_bytes, PD 34);
                                        #   the resolver decodes strict UTF-8 → else KeySourceError (PD 3)
    stdin_is_tty: bool
    prompter: Prompter | None           # None: never prompt (non-TTY or --noinput, D3/D35)

class SecretResolver:
    def __init__(self, inspector: StoreInspector, secret_input: SecretInput) -> None
    def existing(self, store: str, source: KeySource | None) -> Secret | None
        # plaintext store + source → NotEncryptedError; plaintext + None → None
        # encrypted + source → read text (file or stdin) → inspector.parse_secret
        # encrypted + None → prompt "Key or passphrase for store 'x'" or KeyRequiredError (hint: -k)

type NewSecretChoice = NewKeyFile | GenerateKeyFile | NewPassphrase
    # NewKeyFile(source: KeySource), GenerateKeyFile(path: Path), NewPassphrase()
@dataclass(frozen=True, slots=True, kw_only=True)
class NewSecret:
    secret: Secret = field(repr=False)
    generated: Path | None
    def discard(self) -> None           # unlinks a generated key file; only called per PD 33

resolve_new_secret(choice: NewSecretChoice, secret_input: SecretInput) -> NewSecret
    # NewKeyFile: text must be a key file (parse_key) → KeyMaterial
    # GenerateKeyFile: generate_key + write_key_file (0600, O_EXCL)
    # NewPassphrase: see the decision table below
```

- `NewPassphrase` decision table (spec §6.3, D35):

  | stdin is a TTY | prompter | result |
  |---|---|---|
  | no | any | `read_stdin()` (which claims stdin); one trailing LF / CRLF stripped like a passphrase file (D3) |
  | yes | present | `prompter.new_secret(...)` (asked twice) |
  | yes | `None` (`--noinput`) | `KeyRequiredError` (exit 4) — stdin is never read from a terminal |

  The same rule applies to `existing()` with `KeyStdin`: `-k -` reads stdin through `read_stdin` whatever the TTY
  state (the user asked for it explicitly).
- Reading a key or passphrase file that does not exist or cannot be read, and secret text that is empty or not
  UTF-8, raise the new `KeySourceError(CryptoError)` (exit code 4, PD 3) naming the path, never the content.
- The resolver never caches across invocations and never stores keys (D3).
- `NewSecret.discard()` removes the generated file (`missing_ok`). *When* to call it is a CLI rule (PD 33, C1
  `cli/secrets.py`): the library never deletes a key file on its own.

#### `library/` — the public API (spec §7.3)

```text
type KeyInput = Path | KeyMaterial | Passphrase        # a plain str is refused (PD 12)

@dataclass(frozen=True, slots=True)
class Source:                                          # the public one; core's Source stays internal
    name: str                                          # positional: Source("base_conf")
    _: KW_ONLY
    key: KeyInput | None = field(default=None, repr=False)   # keyword only: Source("a", key=Path(...))

type AdapterOpener = Callable[[str, SetupMode], Adapter]
def open_configured_adapter(connection: str, setup: SetupMode) -> Adapter   # open_adapter(connection, setup=setup)

class EnvironmentStore:
    def __init__(self, connection: str, *, setup: SetupMode = SetupMode.AUTO,
                 clock: Clock = utc_now, kdf_params_factory: Callable[[], KdfParams] | None = None,
                 opener: AdapterOpener = open_configured_adapter) -> None
    @classmethod from_env(cls, *, environ: Mapping[str, str] | None = None,
                          setup: SetupMode = SetupMode.AUTO) -> Self          # ENV_STORE_CONNECTION only
    @classmethod from_settings(cls, settings: Settings, **same keywords) -> Self
    # lifetime
    close() -> None (idempotent); closed: bool; __enter__ -> Self; __exit__(...) -> None
    __repr__ -> "EnvironmentStore(scheme='sqlite')"      # never the connection string
    # stores
    list_stores() -> list[StoreInfo]
    store_info(name) -> StoreInfo                                      # StoreNotFoundError
    create_store(name, *, encrypt: bool = False, key: KeyInput | None = None) -> StoreInfo
    delete_store(name) -> None
    copy_store(src, dst, *, key=None, encryption: Literal["same", "plain"] | KeyInput = "same",
               to: EnvironmentStore | None = None) -> StoreInfo
    move_store(...same...) -> StoreInfo
    # variables
    variables(store, *, key=None) -> dict[str, str]
    get(store, name, *, key=None) -> str                               # VariableNotFoundError
    set(store, name, value, *, key=None, overwrite=False) -> None
    set_many(store, values: Mapping[str, str], *, key=None, overwrite=False) -> None
    delete(store, names: Collection[str], *, key=None) -> None
    # encryption (D4)
    encrypt_store(store, *, key: KeyInput) -> None
    rekey_store(store, *, old: KeyInput, new: KeyInput) -> None
    secret_for(store, key: KeyInput) -> Secret
    parse_secret(store, text) -> Secret
    # loading, schema
    load(sources: Sequence[Source | str], *, order: MergeOrder = MergeOrder.LAST_WINS) -> Environment
    migrate() -> MigrationReport          # ValidationError for backends without a schema (files)

@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    stores: tuple[tuple[str, Mapping[str, str]], ...] = field(repr=False)   # load order
    order: MergeOrder
    def variables(self) -> dict[str, str]                 # merged (core.merge), store order (PD 13, D52)
    def with_sources(self) -> dict[str, tuple[str, str]]  # name → (value, winning store), sorted
    def nested(self) -> dict[str, dict[str, str]]         # store order kept, variables sorted
    def nested_flat(self) -> dict[str, str]               # D30, collision → ValidationError
    def apply(self, *, overwrite: bool = False, nested: bool = False,
              environ: MutableMapping[str, str] | None = None) -> dict[str, str]   # returns what it set
    def dumps(self, fmt: Format, *, nested: bool = False) -> str
    def to_file(self, path: Path | str, *, fmt: Format | str | None = None,
                nested: bool = False, force: bool = False) -> None

write_output_file(path: Path, text: str, *, force: bool) -> None
    # without force: O_CREAT | O_EXCL, 0600 → existing file: ValidationError (PD 4)
    # with force: temp file (0600) in the same directory + os.replace
    # any other OSError (missing directory, EACCES, EISDIR, ENOSPC, failed replace) → BackendError
    #   "cannot write '<path>': <strerror>", chained; the partial O_EXCL file or the temp file is unlinked
    #   on every failure, so no decrypted data is left behind (PD 35, mirrors crypto.write_key_file)
read_input_file(path: Path) -> str
    # strict UTF-8, no newline translation; OSError → BackendError "cannot read '<path>': <strerror>";
    #   not UTF-8 → ValidationError naming the path (PD 35; used by `import -f`)
generate_key_file(path: Path) -> None ; generate_key_text() -> str

def load(*stores: str, connection: str | None = None, keys: Mapping[str, KeyInput] | None = None,
         first_wins: bool = False, overwrite: bool = False, nested: bool = False,
         use_project: bool = True, noinput: bool = False) -> Environment          # D36
```

- **Wrapping and lifetime (decided here):** `EnvironmentStore` owns exactly one adapter, opened in `__init__` as
  `opener(connection, setup)` (fail fast: a refused schema or a missing extra surfaces at construction), and one
  `StoreService` over it. `close()` closes the adapter; every method after `close()` raises
  `ValidationError("closed")`. It is a context manager; the CLI registers it with the command's typer context so
  it is closed even on errors.
- **Test seam:** `opener` is the only injection point for adapters. The default `open_configured_adapter` calls
  `core.connection.open_adapter` with the real registry. Tests pass a callable that returns a ready adapter, e.g.
  `lambda _url, setup: backend.open(setup=setup)` for a `MemoryBackend` (`tests/support/memory_adapter.py`,
  unchanged) or the CLI harness's `HookedAdapter` opener (C1). No module-level registry, no fake URL schemes:
  `scheme_of(connection)` still runs (invalid strings are refused, `repr` shows the scheme), but the test opener
  may ignore the string.
- `KeyInput` semantics (PD 12): for an **existing** store a `Path` is read and interpreted by the store's mode,
  exactly like CLI `-k` (`parse_secret`); for a **new** secret (`create_store`, `encrypt_store`, `rekey_store`
  `new`, `copy_store` `encryption`) a `Path` must be a key file (keyfile mode); a passphrase is passed as
  `Passphrase(...)`. `create_store(key=...)` without `encrypt=True`, or `encrypt=True` without `key` →
  `ValidationError`.
- `Environment.apply` (PD 14) does not overwrite variables already in the environment unless `overwrite=True`, like
  `run` and `export-shell`.
- `to_file` infers the format from the extension (`infer_format`); no inference and no `fmt` → `ValidationError`
  ("use fmt / -t"). The text is built before the file is opened, so a refused dotenv value (D37) never leaves a
  file behind.
- One-liner `load()` (D36): `resolve_settings` with `os.environ` and `Path.cwd()`; stores from the arguments or
  the project file (none → `ConfigurationError`); keys: `keys=` > project `[keys]`; prompts with
  `GetpassPrompter` only when `sys.stdin.isatty()` and not `noinput`; applies to `os.environ`; closes the store;
  each `Settings.warnings` entry is emitted with `warnings.warn(..., CredentialsInProjectFileWarning)`
  (a `UserWarning` subclass exported from the package). It is a thin wrapper over
  `library.oneliner.load_with(*, environ, cwd, boundary, uid, interactive, prompter, target, opener, ...)`, which
  the tests drive with fakes. The project file trust check (PD 32) applies here too.
- `environment_store/__init__.py`: `__all__` = `__version__`, `EnvironmentStore`, `Environment`, `Source`,
  `KeyInput`, `load`, `generate_key_file`, `generate_key_text`, `CredentialsInProjectFileWarning`,
  `KeyMaterial`, `Passphrase`, `Secret`, `StoreInfo`, `KeyMode`, `MergeOrder`, `Format`, `SetupMode`,
  `MigrationReport` and every error class of `core.errors`. Resolved lazily through module `__getattr__`
  (PD 1) with the same names imported under `if TYPE_CHECKING:` for type checkers.
- `core/errors.py` gains `KeySourceError(CryptoError)` (PD 3); `tests/unit/core/test_errors.py` is extended.
- `core/connection.py` gains `CREDENTIAL_PARAMETERS` and `connection_has_credentials` (PD 9), tested in
  `tests/unit/core/` by table (userinfo with and without password, `password`, `sslpassword`, encoded names,
  other parameters, non-URL strings → false).

**Tests (L1):**

- `tests/unit/config/test_project.py`: discovery in cwd, in a parent, nearest wins, directory named like the file
  skipped, boundary respected, none found; trust check (PD 32): the test's own file with `uid=os.geteuid() + 1`
  and a world-writable file (`chmod` in `tmp_path`) → untrusted, not read, reason names the file, search does not
  continue upwards; the pure helper `untrusted_reason(st_uid, st_mode, uid)` by table (own uid, root, other uid,
  world-writable, group-writable allowed); schema table (parametrised: unknown key, wrong types, invalid store
  names in `stores` and `[keys]`, empty strings, key material instead of a path, TOML syntax error, unreadable
  file) → `ConfigurationError` without echoing values; key paths relative to the file and `~` expanded;
  `anchor_connection` table (relative/absolute/`~` for json, toml, sqlite; postgres untouched).
- `test_settings.py`: precedence tables for connection and merge order (every combination of option / env / file /
  default); D29 message names the three ways; `parse_bool_setting` values via the env var; empty env var is unset;
  password warning for userinfo, `?password=`, `?sslpassword=` and a percent-encoded name (`pass%77ord=`), also when
  overridden, absent with `--no-project`, never containing the password; untrusted project file → warning only, its
  connection / stores / keys unused; `repr(Settings)` hides the connection.
- `test_secrets.py`: with a `MemoryAdapter`-backed `EnvironmentStore` (cheap KDF): file / stdin / prompt per mode;
  key file for a passphrase store → `KeyModeMismatchError`; source for a plaintext store → `NotEncryptedError`; no
  source and no prompter → `KeyRequiredError` with the `-k` hint; unreadable / missing / non-UTF-8 / empty secret
  file → `KeySourceError`; `resolve_new_secret` for each choice incl. piped passphrase, prompted passphrase, the
  `NewPassphrase` decision table (non-TTY → stdin, TTY + prompter → prompt, TTY without prompter →
  `KeyRequiredError` and `read_stdin` never called); generated file is `0600` and `discard()` removes it; refuses an
  existing path; secrets never in `repr` or messages (Hypothesis: random secrets never appear in `str(err)`).
- `tests/unit/library/`: every `EnvironmentStore` method against a `MemoryBackend` through `opener` (plus one smoke
  per real scheme json/toml/sqlite through the default opener); `Source("a")` positional and `Source("a", key=...)`,
  `Source("a", Path(...))` → `TypeError`; lifetime (context manager closes the adapter, use after close, idempotent
  close, construction errors propagate and leak nothing); `from_env` with and without the variable; `KeyInput` rules
  (Path / KeyMaterial / Passphrase / str refused); `Environment` merge orders, sources, nested, nested-flat
  collision, `apply` with and without overwrite, `dumps` per format, `to_file` refuse / force / `0600` / inference /
  no file left on a refused value; `write_output_file` atomic replace, missing directory, read-only directory, a
  target that is a directory and a forced `os.replace` failure (monkeypatched) → `BackendError` with the path and no
  file or temp file left; `read_input_file` missing / directory / non-UTF-8 / CRLF content kept exactly; one-liner
  via `load_with` (project stores, explicit stores, keys precedence, prompt only when interactive, `noinput` →
  `KeyRequiredError`, warning emitted with `pytest.warns`, store closed afterwards) and one test of the public
  `load()` with `monkeypatch` (`chdir`, `setenv`, `getpass.getpass`); Hypothesis round-trip `apply`/`to_file` → read
  back equals `variables()`.
- `tests/unit/test_package.py`: every name in `environment_store.__all__` resolves; unknown attribute →
  `AttributeError`; `import environment_store` in a fresh interpreter loads neither `library` nor `config`
  (laziness).

### C1 · CLI foundation (item 11)

**Covers:** D19, D20, D24 (exit codes), D3 (key input rules, no literal keys), D16 (positional store lists, `-k
store=path`), D17 (project file in the CLI), D33 (conventions: stdout / stderr, `-y`, `--json`, `-k` shorthand,
`-s` for writing commands), D35 (`--noinput`), D11 / D13 (`migrate`), spec §6 conventions and §6.0.

#### Packaging (C1 is sequential and may edit `pyproject.toml`)

- `[project.scripts]`: `environment-store = "environment_store.cli:main"`, `envs = "environment_store.cli:main"`
  (D20); remove the placeholder comment.
- `cli` extra, the `typer` entry of `all` and the testing group: `typer>=0.26` (PD 15); `uv lock`.
- New `tests/unit/test_extras.py` (reads `pyproject.toml` with `tomllib`): every requirement of every other extra
  appears verbatim in `all`, and `all` contains nothing else. It passes before C1 (both say `typer>=0.15`,
  `textual>=3`) and guards the floors raised by C1 and T1.

#### Modules and interfaces

```text
# cli/__init__.py — imports no typer
def main() -> None
    # imports environment_store.cli.app lazily; MissingExtraError → message on stderr, exit 1
# cli/app.py — module-level guard: a missing typer raises MissingExtraError("cli") on import
def build_app() -> typer.Typer      # typer.Typer(cls=EnvsGroup, pretty_exceptions_enable=False,
                                    #   rich_markup_mode=None, no_args_is_help=True)
app: typer.Typer = build_app()

# cli/_typer.py
class EnvsGroup(TyperGroup):        # make_context / invoke overridden:
    # typer.TyperException (vendored click usage errors: unknown option or command, missing argument,
    #   bad choice) → exit_code set to 1 (spec: usage error = 1; click's default 2 means "not found" here)
    # EnvironmentStoreError → "Error: <message>" on stderr, typer.Exit(exit_code_for(err))
class EnvsCommand(TyperCommand):
    # invoke(ctx) calls get_state(ctx).settings() before the command callback (PD 10). invoke runs only after
    #   the command's own arguments were parsed, so `envs <cmd> --help` (handled while parsing) never resolves
    #   settings. Every command is registered with cls=EnvsCommand (or PassthroughCommand)
class PassthroughCommand(EnvsCommand):
    # parse_args splits at the first "--": the tail goes to ctx.meta["passthrough"] (used by run, C4)

# cli/runtime.py — every terminal / OS boundary, injectable through CliRunner.invoke(..., obj=Runtime(...))
type ExecProcess = Callable[[str, list[str], Mapping[str, str]], NoReturn]   # list: typeshed's execvpe argv
def _environ() -> Mapping[str, str]: return os.environ
def _stdin_is_tty() -> bool: return sys.stdin.isatty()     # named functions, not lambdas (ruff PLW0108)
def _stdout_is_tty() -> bool: return sys.stdout.isatty()   #   and not bound methods (looked up at call time)
@dataclass(frozen=True, slots=True, kw_only=True)
class Runtime:
    environ: Callable[[], Mapping[str, str]] = _environ
    cwd: Callable[[], Path] = Path.cwd
    project_boundary: Path | None = None
    uid: int | None = None                      # None → os.geteuid() (project file trust, PD 32)
    stdin_is_tty: Callable[[], bool] = _stdin_is_tty
    stdout_is_tty: Callable[[], bool] = _stdout_is_tty
    prompter: Prompter | None = None            # None → TerminalPrompter()
    exec_process: ExecProcess = os.execvpe
    clock: Clock = utc_now
    kdf_params_factory: Callable[[], KdfParams] | None = None
    adapter_opener: AdapterOpener = open_configured_adapter

# cli/state.py
@dataclass(slots=True, kw_only=True)
class CliState:                     # created by the root callback, stored in ctx.obj
    runtime: Runtime; connection_option: str | None; use_project: bool; noinput: bool
    def settings(self) -> Settings                 # cached; prints each warning once to stderr; called by
                                                   #   EnvsCommand for every command (PD 10)
    def open_store(self, ctx: typer.Context, *, setup: SetupMode = SetupMode.AUTO,
                   connection: str | None = None) -> EnvironmentStore   # ctx.with_resource
    def interactive(self) -> bool                  # stdin is a TTY and not --noinput
    def secret_input(self, purpose: str) -> SecretInput   # stdin_is_tty from Runtime; prompter only when
                                                   #   interactive(); its read_stdin = claim_stdin(purpose) +
                                                   #   read_stdin_bytes()
    def claim_stdin(self, purpose: str) -> None    # 2nd claim → ValidationError naming both
    def read_stdin_bytes(self) -> bytes            # typer.get_binary_stream("stdin").read() (PD 34)
    def read_stdin(self) -> str                    # read_stdin_bytes().decode("utf-8") strict, no newline
                                                   #   translation; UnicodeDecodeError → ValidationError
def get_state(ctx: typer.Context) -> CliState

# cli/options.py — Annotated aliases, all options keyword-only in command signatures (ruff FBT)
StoresArg, StoreOpt (-s/--store, required), ReadKeysOpt (-k/--key, repeatable), WriteKeyOpt (-k/--key),
FirstWinsOpt, OverwriteOpt (-o/--overwrite), NestedOpt, JsonOpt (--json), YesOpt (-y/--yes),
FileOpt (-f/--file), TypeOpt (-t/--type, Format choices), ForceOpt, NewKeyOpt (--new-key),
GenerateKeyOpt (--generate-key), PassphraseOpt (--passphrase), CreateKeyOpt (-k/--key for create-store)

# cli/errors.py
class ExitCode(IntEnum): OK = 0, USAGE = 1, NOT_FOUND = 2, EXISTS = 3, KEY = 4, CONFLICT = 5
def exit_code_for(error: EnvironmentStoreError) -> ExitCode   # by category class (B2 table)

# cli/key_options.py
def parse_reading_keys(values: Sequence[str], stores: Sequence[str]) -> dict[str, KeySource]
def parse_writing_key(value: str | None) -> KeySource | None
# cli/secrets.py
def existing_secret(ctx, store: str, key: str | None) -> Secret | None
    # -k path|- > project [keys] (PD 5) > prompt (interactive) > KeyRequiredError
def new_secret(ctx, *, key: str | None, generate: Path | None, passphrase: bool,
               key_option: str) -> NewSecret | None     # exactly one, else ValidationError;
    # generate == Path("-") → ValidationError "--generate-key needs a file path; use 'envs keygen -' and
    #   '<key_option> -'" for every command (create-store, cp-store, mv-store, rekey, encrypt; PD 24)
@contextmanager
def keep_or_discard(new: NewSecret | None, *, target: str, store: EnvironmentStore,
                    creates_target: bool) -> Iterator[None]
    # wraps the writing library call; on an exception decides per PD 33 whether to call new.discard() or keep
    #   the file and print "kept generated key file '<path>'; store '<target>' may already be encrypted with it"
    #   on stderr; the exception is always re-raised
# cli/loading.py
def load_for_reading(ctx, *, stores: Sequence[str] | None, keys: Sequence[str] | None,
                     first_wins: bool) -> Environment
# cli/confirm.py
def require_confirmation(ctx, question: str, *, yes: bool) -> None
# cli/output.py
def out(text: str = "", *, newline: bool = True) -> None ; def err(text: str) -> None
def emit_json(data: JsonValue) -> None                # sort_keys, ensure_ascii=False, one document
def table(rows: Sequence[Sequence[str]]) -> str       # columns aligned, two spaces
def display_value(value: str) -> str                  # single-line printable as is, else JSON string
def write_value(value: str, *, tty: bool) -> None     # raw value, newline only on a TTY (D33, §6.7)
# cli/prompts.py — no typer.prompt / typer.confirm (they write part of the prompt and the echo to stdout)
@dataclass(frozen=True, slots=True, kw_only=True)
class TerminalPrompter:
    read_hidden: Callable[[str], str] = <getpass.getpass with stream=sys.stderr, looked up at call time>
    read_line: Callable[[], str] = <sys.stdin.readline at call time>   # named module functions, as in runtime
    write: Callable[[str], None] = <sys.stderr.write + flush at call time>
    # secret: read_hidden(prompt + ": "); new_secret: asked twice, mismatch → "values do not match" on stderr
    #   and asked again, the third mismatch → ValidationError (exit 1); confirm: write(question + " [y/N]: "),
    #   read_line(), only y / yes (case-insensitive) is yes
    # EOF (EOFError from getpass, "" from readline) → typer.Abort (exit 1); KeyboardInterrupt is not caught
```

#### Rules C1 implements and tests

- **Global options** on the root callback: `-c/--connection`, `--no-project`, `--noinput`, `--version`
  (eager, prints `environment-store <version>`, needs no connection — PD 16), `--help`. The root callback only
  builds `CliState`; it never resolves settings.
- **Where settings are resolved (PD 10):** `EnvsCommand.invoke` calls `get_state(ctx).settings()` for every
  command before its callback, so a broken project file or a bad `ENV_STORE_ORDERED_OVERWRITE` fails every
  command (`keygen` and `ls-store` included) with exit 1, and the password / untrusted-file warnings are printed
  once per command. `envs --help`, `envs <cmd> --help` and `--version` never reach it. The connection itself
  (`Settings.require_connection()`, D29) is required by `CliState.open_store`, i.e. by every command that opens a
  store; `keygen` opens none (PD 17).
- **Store lists** (§6.0.1): positional stores replace the project file's `stores`; none on either side →
  `ValidationError` ("name stores or set `stores` in .envstore.toml"). Names validated before any I/O. Repeats are
  allowed (load order), but a store is prompted for at most once (PD 18).
- **`-k` for reading commands**: `-k store=path`, `-k store=-`; `-k path` / `-k -` only when the effective list
  has exactly one store (D33). A value is `store=path` when the part before the first `=` is a valid store name,
  otherwise a bare path (PD 19). Errors (all exit 1): store not in the list, two `-k` for one store, empty path,
  shorthand with several stores, more than one stdin (`-` ) per command (D3). `-k` for a plaintext store →
  `NotEncryptedError` (exit 1). Project `[keys]` for stores that are not loaded are ignored; for a loaded plaintext
  store they are an error too (PD 5).
- **Order of work for reading:** validate names and `-k`, check all stores exist (one `list_stores`), then resolve
  secrets in load order (prompts), then load — so a typo never costs a prompt (PD 18). A wrong key is not
  re-prompted.
- **`-k` for writing commands** (`-s`): a path or `-` only (PD 19).
- **`--generate-key -`** is refused by `new_secret` for every command that takes the option (PD 24).
- **Generated key files** are deleted after a failure only when the store provably does not use them
  (`keep_or_discard`, PD 33).
- **stdin is consumed by at most one thing** per command (`-k -`, `--new-key -`, piped `--passphrase`, `set`
  value, `import` input): `claim_stdin` refuses the second with exit 1 (spec §6.8 "stdin and `-k -` can't be used
  together", generalised).
- **Interaction** (D3, D35): prompts only when stdin is a TTY and `--noinput` is not set; prompts and
  confirmations go to **stderr** through `TerminalPrompter` (PD 20) and nothing of a prompt or its echo reaches
  stdout; output goes to stdout. A missing secret where a prompt is not allowed →
  `KeyRequiredError` (exit 4, hint `-k`). `require_confirmation`: `--yes` → proceed; interactive → ask, "no" →
  exit 1; otherwise → `ValidationError` naming `-y` (exit 1).
- **Exit codes** (D24): category mapping as in the B2 table; usage errors from typer → 1 (EnvsGroup); EOF at a
  prompt → `typer.Abort` → 1; Ctrl-C → 130 everywhere, also at a prompt, because `TerminalPrompter` does not catch
  `KeyboardInterrupt` and typer turns an escaping one into 130 (PD 21); `run` passes through (C4). No traceback for
  an `EnvironmentStoreError`; unexpected exceptions keep their traceback (no rich locals).
- **Output conventions**: success diagnostics are one line on stderr (e.g. `created store 'x'`); data on stdout
  only; `--json` emits exactly one JSON document on stdout with a trailing newline.
- **`migrate`** (D11, D13): opens with `SetupMode.NONE`, calls `EnvironmentStore.migrate()`; prints `created schema
  v1`, `upgraded schema from v1 to vN` or `schema is up to date (vN)` on stderr; file backends → `ValidationError`
  ("migrate applies to SQL backends only", PD 22); foreign / newer schema → exit 1.

#### Test harness (shared with C2–C4)

- `tests/cli/conftest.py`: autouse fixture deleting `ENV_STORE_CONNECTION` and `ENV_STORE_ORDERED_OVERWRITE` and
  `chdir`ing to `tmp_path`; fixture `cli` parametrised over `json`, `toml`, `sqlite` (`cli_json` for single-backend
  error tests).
- `tests/support/cli.py`:

  ```text
  @dataclass
  class CliHarness:
      root: Path; connection: str; clock: FakeClock; kdf: CheapKdf
      exec_calls: list[tuple[str, list[str], dict[str, str]]]
      def runtime(self, *, stdin_tty: bool = False, stdout_tty: bool = False,
                  prompter: Prompter | None = None, opener: AdapterOpener | None = None) -> Runtime
      def invoke(self, *args: str, input: str | bytes | None = None, env: Mapping[str, str] | None = None,
                 stdin_tty: bool = False, stdout_tty: bool = False, connection: bool = True,
                 prompter: Prompter | None = None, opener: AdapterOpener | None = None) -> Result
          # passes -c <connection> unless connection=False; project_boundary = root; prompter defaults to a
          #   RecordingPrompter with no answers (any prompt fails the test)
      def hooked_opener(self, *, before: Mapping[str, Callable[[], None]] | None = None,
                        after: Mapping[str, Callable[[], None]] | None = None) -> AdapterOpener
          # opens the real adapter for `connection` and wraps the FIRST adapter it opens in a HookedAdapter;
          #   later opens (e.g. harness.store() inside a hook) are returned unwrapped
      def store(self) -> EnvironmentStore          # arrange / assert through the library, same backend
      def key_file(self, name: str = "a.key") -> Path
      def passphrase_file(self, text: str, name: str = "p.txt") -> Path
      def project_file(self, text: str, *, directory: Path | None = None) -> Path
  class RecordingPrompter: answers queue (a str, or an exception instance to raise, e.g. KeyboardInterrupt(),
      EOFError() → typer.Abort), records prompts; fails the test when it runs out
  class HookedAdapter: delegates every Adapter method to an inner adapter; `before[method]` runs once right
      before the first call of that method, `after[method]` once right after it returned (a hook may raise).
      Exit 5: before={"write_store": lambda: harness.store().set("a", "RACE", "1")}. Failure after a commit:
      after={"write_store": raising(BackendError("connection lost"))} (helper in the same module).
      Per-instance state only, nothing to reset between tests.
      Named differently from the service tests' RacingAdapter (tests/unit/service/conftest.py), which stays.
  class Executed(Exception): raised by the fake exec_process after recording the call
  ```

  `CheapKdf` lives in `tests/support/kdf.py` (moved there by L1) and is shared by service, library and CLI tests.
- Hypothesis in CLI tests creates one temporary backend per example inside the test body (no function-scoped
  fixture per example).

**Tests (C1)** in `tests/cli/foundation/`, using a test-only app from `build_app()` plus test commands where a
real command does not exist yet:

- entry points: `importlib.metadata.entry_points(group="console_scripts")` maps both names to
  `environment_store.cli:main`; `main()` with `sys.argv` patched exits with the command's code; `__main__` both
  branches (`runpy` with `run_name="__main__"` and a plain import, §6.3); with `sys.modules["typer"] = None`,
  `import environment_store.cli.app` raises `MissingExtraError("cli")` and `main()` prints the hint and exits 1;
  `import environment_store.cli` alone never imports typer (fresh interpreter).
- usage errors (unknown command, unknown option, missing argument, bad `-t` choice, no arguments) → exit 1, message
  on stderr, nothing on stdout (except the help for no arguments).
- `exit_code_for` table for every error class in `core.errors`; one end-to-end command per exit code 0–5
  (5 through `HookedAdapter`); a `RecordingPrompter` raising `KeyboardInterrupt` → 130 and `EOFError` → 1.
- global options: `-c` > env > project file; `--no-project`; D29 message; password warning on stderr once per
  command; `--version` without connection; bad `ENV_STORE_ORDERED_OVERWRITE` → exit 1; with a broken
  `.envstore.toml`: a test command's `--help` and `envs --help` → exit 0 with help on stdout and no warning, the
  test command itself → exit 1, a test command that opens no store (stand-in for `keygen`) → exit 1 as well; the
  same command without any connection → exit 0 (PD 17); untrusted project file → warning, connection unused.
- `parse_reading_keys` / `parse_writing_key` tables (Hypothesis: arbitrary valid store names and paths with `=`);
  `load_for_reading` precedence (`-k` > `[keys]` > prompt), single prompt per repeated store, existence checked
  before prompting, `--noinput` and non-TTY → exit 4 without prompting.
- `claim_stdin` double use; `read_stdin` returns `"a\r\nb\rc\n"` byte-exact (bytes input to `CliRunner`) and
  refuses non-UTF-8 bytes with exit 1; `secret_input` carries `stdin_is_tty` from `Runtime` and its `read_stdin`
  claims stdin; `require_confirmation` matrix (`-y` / TTY yes / TTY no / non-TTY / `--noinput`).
- `new_secret`: exactly one option, `--generate-key -` refused with the hint; `keep_or_discard` (PD 33) — a
  `ValidationError` / `CryptoError` / `StoreExistsError` before the write → file removed; a `BackendError` → file
  kept and the path printed; for `creates_target=True` a non-backend error with the target existing afterwards →
  kept.
- `TerminalPrompter` with fake callables: prompt text on `write` only, `new_secret` match / one mismatch then
  match / three mismatches → `ValidationError`, `confirm` answers (`y`, `YES`, `n`, empty), EOF → `typer.Abort`,
  `KeyboardInterrupt` propagates. The three default callables are named module functions, each covered by one
  test with `getpass.getpass` / `sys.stdin` / `sys.stderr` monkeypatched.
- output helpers: `--json` validity, `display_value` for multi-line, `write_value` newline only on a TTY.
- `PassthroughCommand`: tokens after `--` untouched, including `-o` and `--`.
- `migrate` against SQLite: new file → created; current → up to date; foreign database → exit 1, unchanged; a json
  backend → exit 1. One `@pytest.mark.postgres` test: outdated schema refused by a normal command, upgraded by
  `migrate` (reuses `tests/adapters/postgres/server.py`).

### C2 · Store commands (item 12, parallel)

**Covers:** D4 (no decrypt; `--plain` copy is the way), D5 (copies are re-encrypted, need the key), D15, D21, D27,
D33 (`cp-store` / `mv-store` encryption of the target), spec §4.4, §6.2–§6.5.

| Command | Signature |
|---|---|
| `ls-store` | `[--json]` |
| `create-store` | `NAME [-e/--encrypt] [-k/--key PATH\|-] [--generate-key PATH] [--passphrase]` |
| `rm-store` | `NAME [-y/--yes]` |
| `cp-store` | `SRC DST [--to CONNECTION] [-k/--key PATH\|-] [--plain \| --new-key PATH\|- \| --generate-key PATH \| --passphrase]` |
| `mv-store` | same as `cp-store` |

- `ls-store`: human output `table` of `name` and `plain` / `encrypted (keyfile)` / `encrypted (passphrase)` /
  `encrypted (unknown)` (unrecognised mode); no variable count (D1). `--json`: list of
  `{"name", "encrypted", "key_mode", "revision", "created_at", "updated_at"}`, timestamps ISO 8601 UTC with `Z`
  (PD 23). Empty backend → no output, exit 0.
- `create-store`: `-e` needs exactly one key option; a key option without `-e` → exit 1 (PD 24). `-k` must be a key
  file (keyfile mode); `--generate-key` writes the file first; the library call runs inside `keep_or_discard(...,
  creates_target=True)` (PD 33); `--generate-key -` is refused by `new_secret` (PD 24). `--passphrase` per spec §6.3
  (stdin if piped, else asked twice).
- `rm-store`: needs no key (D21); checks the store exists **before** asking (exit 2 without a prompt);
  confirmation through `require_confirmation`.
- `cp-store` / `mv-store`: source key via `existing_secret` (incl. project `[keys]`); target encryption `same`
  (default) / `--plain` / new secret via `new_secret(key_option="--new-key")`; options mutually exclusive;
  `DST == SRC` without `--to` → exit 1; `--to` opens a second `EnvironmentStore` (same runtime, registered on the
  context); `DST` exists → exit 3, nothing changed; the copy / move runs inside
  `keep_or_discard(..., target=DST, store=<target store>, creates_target=True)` (PD 33), so a generated key file is
  removed only when `DST` provably does not exist.

**Tests (C2)** `tests/cli/stores/`: per command the happy path on json, toml and sqlite; `--json` schema;
encrypted listing shows mode, never a count; create plain / `-k` / `-k -` / `--generate-key` (file `0600`) /
`--passphrase` piped and prompted (`RecordingPrompter.new_secret`) / `--noinput` on a TTY → exit 4 without reading
  stdin / `--generate-key -` → 1 and no file named `-`; duplicate → 3;
invalid name → 1 and nothing created; key options without `-e` → 1; `rm-store` of an encrypted store without a key
(D21), missing → 2 without prompt, non-TTY without `-y` → 1, TTY "no" → 1 and store kept; `cp-store` same key
(target decrypts with the source key, ciphertext differs: D5), `--plain` (the documented decrypt path, D4),
`--new-key`, `--generate-key`, `--passphrase`; wrong key → 4; plain source with `-k` → 1; `--to` another backend
(json → sqlite) incl. `DST == SRC`; `mv-store` removes the source and keeps it when the copy fails (destination
exists → 3) or the source changes during the move (`HookedAdapter` → 5); `--generate-key` for `cp-store` /
  `mv-store` with `DST` existing → 3 and the key file removed; `mv-store --generate-key` with
  `before={"delete_store": raising(BackendError(...))}` (the copy is committed, then deleting `SRC` fails) → exit 1,
  the key file is kept, its path is on stderr and it decrypts `DST`.

### C3 · Variable commands (item 13, parallel)

**Covers:** D1 (`ls` needs the key), D14, D16, D18, D22 (`import` defaults), D28 (values), D33 (`get` raw output,
`import` flat input only, writing commands via `-s`), D37 (import never interpolates), spec §6.6–§6.10.

| Command | Signature |
|---|---|
| `ls` | `[STORES...] [-v/--values] [--source] [--first-wins] [-k STORE=PATH ...] [--json]` |
| `get` | `KEY [STORES...] [--first-wins] [-k STORE=PATH ...] [--json]` |
| `set` | `-s STORE [-o/--overwrite] [-k PATH\|-] ARGS...` |
| `rm` | `-s STORE [-k PATH\|-] KEYS...` |
| `import` | `-s STORE [-f/--file PATH\|-] [-t/--type dotenv\|json\|toml] [-o/--overwrite] [-k PATH\|-]` |

- `ls`: `load_for_reading`; names in merged order (PD 13, D52), one per line; `-v` → `NAME=display_value(value)`; `--source` adds
  the winning store as a second column; `--json` → list of `{"name"[, "value"][, "store"]}` with the keys present
  only when requested (PD 23).
- `get`: variable name validated first; raw value via `write_value` (no trailing newline unless stdout is a TTY,
  D33); missing everywhere → exit 2; `--json` → `{"name", "value", "store"}`.
- `set` (D18): `ARGS` are either all `KEY=VALUE` (split at the first `=`, empty value allowed) or exactly one `KEY`;
  mixed or several bare keys → exit 1. `KEY=VALUE` on an encrypted store → `PlaintextNotAllowedError` (exit 1)
  with the stdin / prompt hint, checked before reading any key. One bare `KEY`: value from stdin when stdin is not a
  TTY **or** `--noinput` is set (D35), otherwise the hidden prompt asked twice; stdin claimed (so `-k -` is
  refused); a stdin value is decoded as strict UTF-8 without newline translation and loses exactly one trailing
  newline (LF or CRLF, D38, PD 25); the hidden prompt drops the line ending of what was typed. One write, one revision; existing
  variables without `-o` → exit 3 listing all, nothing written.
- `rm`: one write; missing variables → exit 2 listing all, nothing written; no confirmation (PD 26).
- `import`: `-f` omitted or `-` → stdin (claimed, read through `CliState.read_stdin`, PD 34); a file through
  `read_input_file` (PD 35); `-t` omitted → `infer_format(file)`, dotenv for stdin, no
  inference → exit 1; parsed with `formats.*.loads` (flat strings only, nested refused: D33; dotenv never
  interpolates: D37); conflicts without `-o` → exit 3, nothing written; an empty document → no write, exit 0
  (PD 27); missing, unreadable or directory input file → exit 1 with the path, no traceback; non-UTF-8 → exit 1.

**Tests (C3)** `tests/cli/variables/`: happy paths on json, toml and sqlite; merge across stores with and without
`--first-wins`, `ENV_STORE_ORDERED_OVERWRITE=false`, project `ordered_overwrite`; project store list used and
replaced by positional stores; `--source`; encrypted stores with `-k store=path`, `-k store=-`, shorthand, project
`[keys]`, prompt (TTY) and exit 4 without; wrong key → 4; `get` raw output without newline when piped, with newline
on a TTY, multi-line values exact; `get` missing → 2; `--json` for `ls` and `get`; `set` every form, the refusal on
encrypted stores, stdin + `-k -` → 1, `--noinput` reads stdin, `-o`, conflict → 3 with all names; `rm` several,
missing → 2, nothing written; `import` per format, inference, stdin default, nested JSON refused, `${X}` stored
literally, conflicts → 3, `-o`; concurrent change → 5 (`HookedAdapter`); Hypothesis: any value (D28, incl. `\r` and `\r\n`
inside) piped as bytes through `set` (stdin) with one appended `\n` → `get` is identical (D38); explicit cases:
`"abc\n"` stores `abc`, `"abc\r\n"` stores `abc`, `"abc\n\n"` stores `abc\n`, `"abc\r"` stays `abc\r`, `"a\r\nb"`
stays; a PEM block ending in a newline round-trips exactly through `import`; `import -f` of a missing file and of a directory → 1;
Hypothesis: `export -t F` → `import -t F` round-trips for every format (C3 may call
`export` only through the library `Environment.dumps`, since `export` is C4's command).

### C4 · Export, run and key commands (item 14, parallel)

**Covers:** D2, D4, D14, D15 (`run`), D22 (`export` defaults), D23 (POSIX shells), D30 (nested keys), D33 (`run`
exit code and `execvpe`, `keygen` format), D34 (passphrase mode via `rekey` / `encrypt`), D37 (dotenv quoting and
refusals), spec §4.5, §6.11–§6.13.

| Command | Signature |
|---|---|
| `export` | `[STORES...] [-f/--file PATH\|-] [-t/--type ...] [--force] [--nested] [--first-wins] [-k STORE=PATH ...]` |
| `export-shell` | `[STORES...] [-o/--overwrite] [--nested] [--first-wins] [-k STORE=PATH ...]` |
| `run` | `[STORES...] [-o/--overwrite] [--nested] [--first-wins] [-k STORE=PATH ...] -- CMD [ARGS...]` |
| `keygen` | `PATH\|-` |
| `rekey` | `-s STORE [-k PATH\|-] (--new-key PATH\|- \| --generate-key PATH \| --passphrase)` |
| `encrypt` | `-s STORE (--new-key PATH\|- \| --generate-key PATH \| --passphrase)` |

- `export`: `-f` omitted or `-` → stdout (D22); `-t` omitted → inferred, dotenv for stdout, no inference → exit 1;
  `--nested` → `nested()` for JSON / TOML, `nested_flat()` for dotenv (D30, collision → exit 1); the file is
  written with `write_output_file` (`0600`, PD 4): existing file without `--force` → exit 1, with `--force`
  replaced atomically; D37 refusals → exit 1 with the hint and no file written. `--force` with stdout is accepted
  and has no effect.
- `export-shell`: `posix_exports(..., overwrite=...)`; `--nested` → `nested_flat()`; invalid shell names → exit 1
  (since D40 a store name always yields a valid nested prefix, so only non-merge sources can trigger it, if any).
- `run` (`cls=PassthroughCommand`): no `--` or an empty command → exit 1 (PD 28). Environment = current
  environment plus the merged (or nested-flat) variables, existing variables kept unless `-o`. Then the store is
  closed, stdout / stderr flushed and `runtime.exec_process(cmd[0], cmd, env)` replaces the process (POSIX,
  D33). `FileNotFoundError` → message, exit 127; `PermissionError` → exit 126 (PD 28). On Windows
  (`if sys.platform == "win32":`, excluded from coverage, unverified like A1's `msvcrt` branch):
  `subprocess.run(cmd, env=env, check=False)` and `typer.Exit(returncode)`, with the `# nosec B404` / `# nosec
  B603` + `# noqa: S603` suppressions and justifications given in §6.3 (Windows row).
- `keygen PATH`: `generate_key_file` (`0600`, refuses an existing path → exit 1); `keygen -` prints the key line
  to stdout. Registered with `cls=EnvsCommand` like every command, so settings are resolved (a broken project
  file → exit 1, PD 10), but it opens no store and therefore needs no connection (PD 17).
- `rekey`: old secret via `existing_secret` (`-k`, project `[keys]`, prompt); new via `new_secret(key_option=
  "--new-key")`; the library call runs inside `keep_or_discard(..., creates_target=False)` (PD 33): a generated key
  file is removed only for errors raised before the write (validation, key, not-found, concurrent-modification), and
  kept with its path on stderr after a `BackendError` (the commit may have happened); `encrypt`:
  `AlreadyEncryptedError` → exit 1; `rekey` of a plaintext store → exit 1 (`NotEncryptedError`).

**How `run` is tested:**

1. In-process (`CliRunner`): the harness's fake `exec_process` records `(file, argv, env)` and raises `Executed`;
   tests assert argv after `--` is untouched (incl. `-o`, `--`), merge / nested / overwrite rules on `env`, the
   store is closed before exec, and the 127 / 126 mappings (fake raises `FileNotFoundError` /
   `PermissionError`). The default `exec_process = os.execvpe` is a reference, not a wrapper, so no untestable
   line exists; it type-checks because `ExecProcess` takes argv as `list[str]` (C1), and `run` passes a list.
2. End to end (POSIX, `subprocess.run([sys.executable, "-m", "environment_store.cli", ...])` with
   `ENV_STORE_CONNECTION` pointing at a json backend in `tmp_path`): exit code passthrough (`sys.exit(7)` → 7),
   a variable visible in the child, and `os.getpid()` printed by the child equals the `Popen` pid (the process was
   replaced, so signals reach the command directly). These tests prove behaviour; coverage comes from (1).

**Tests (C4)** `tests/cli/exporting/` and `tests/cli/encryption/`: `export` per format to stdout and file on json,
toml and sqlite; inference from `.env`, `.env.local`, `.json`, `.toml`; unknown extension → 1; existing file → 1
and unchanged; `--force` replaces; mode `0600`; `-f` into a missing directory → 1 with the path, no traceback,
nothing left behind; nested per format incl. the D30 example and a collision; D37
refusals (`${`, `$` in a double-quoted value) → 1, no file; `--first-wins`; encrypted stores with keys and prompts;
golden output for the spec §6.11 examples; `export-shell` output evaluated with `/bin/sh -c 'eval "$OUT"; …'`
reproduces values exactly (Hypothesis), keeps preset variables without `-o`, `set -e` safe; `keygen` file content
and mode, refusal, `keygen -`, no connection needed; `rekey` keyfile → passphrase → keyfile, old key no longer
works, new salt; wrong old key → 4 and generated file removed; `rekey --generate-key` with
`after={"write_store": raising(BackendError(...))}` → exit 1, key file kept and path on stderr, and the store
decrypts with it; `rekey` / `encrypt --generate-key -` → 1 and no file named `-`; `keygen` with a broken
`.envstore.toml` → 1; `encrypt` plain → encrypted then `ls` needs the key
(D1), twice → 1; `--noinput` with `--passphrase` on a TTY → 4; two stdin consumers → 1.

### T1 · TUI (item 15)

**Covers:** D15 (`tui` in V2.0), D31 (built on the library), spec §6.14. The spec requires only that `envs tui`
starts a TUI and fails with an install hint without the `tui` extra; the feature set below is decided here (PD 29).

- Packaging: `tui` extra, the `textual` entry of `all` and the testing group `textual>=8.2` (the tested version
  line, PD 15); `uv lock`; `tests/unit/test_extras.py` (C1) keeps `all` equal to the union of the other extras.
- `tui/__init__.py`: module-level guard → `MissingExtraError("tui")`; exports `run_tui`.
- `tui/app.py`: `class EnvironmentStoreApp(App[None])`, `__init__(self, store: EnvironmentStore, *, key_paths:
  Mapping[str, Path], read_key_file: Callable[[Path], str] = ...)`; `def run_tui(store, *, key_paths) -> None`.
- Screens (`tui/screens/`): `StoresScreen` (table: name, plain / encrypted (mode); `enter` opens),
  `UnlockScreen` (modal: key file path or passphrase input with `password=True`; uses `EnvironmentStore.
  secret_for` / `parse_secret`; project `[keys]` are tried first without asking), `VariablesScreen` (table of
  names, values masked until `v` toggles; `a` add / edit via `EditVariableScreen` with a multi-line `TextArea`,
  `d` delete via `ConfirmScreen`, `r` reload, `escape` back). Errors appear as notifications with the error
  message only; values and secrets never appear in notifications or logs. A conflicting write (D7) asks to reload.
- Out of scope in V2.0 (CLI only): create / delete / copy / move stores, import / export, key lifecycle.
- `cli/tui_command.py`: `envs tui` resolves settings like every command (`EnvsCommand`; connection, project
  `[keys]`), refuses `--noinput` and a non-TTY stdout (exit 1), imports `environment_store.tui` inside the command
  function (the one recorded `cli → tui` edge, PD 31; missing textual → `MissingExtraError` → exit 1 with the
  hint) and calls `run_tui`; registered in `cli/app.py`. T1 adds the `_MODULE_EXCEPTIONS` entry and the two
  direction tests to `tests/unit/test_import_direction.py` (§6.1).
- Tests (`tests/tui/`): Textual Pilot (`async with app.run_test() as pilot`) wrapped in `asyncio.run` inside plain
  pytest functions (no new test dependency, PD 30), against a json backend through `EnvironmentStore` with the cheap
  KDF: list, open plain store, unlock with project key / typed key file path / passphrase, wrong key → notification
  and store stays locked, add / edit multi-line / delete with confirm, masked values, reload after a concurrent
  change; `envs tui` without textual (`sys.modules["textual"] = None`) → exit 1 with the hint, with `--noinput` →
  1, `run_tui` faked in the CLI test. Textual warnings are not silenced globally; a needed
  `pytest.mark.filterwarnings` names the warning and the reason.
- `tests/cli/test_command_table.py`: the §6.1 command set equals the registered commands.

### 6.3 Integration risks and how the plan handles them

| Risk | Handling |
|---|---|
| typer vendors click since 0.26 (installed 0.28.0); `typer._click` is private | Never import `click` or `typer._click`. Only `typer`, `typer.core.TyperGroup` / `TyperCommand`, `typer.TyperException` (base of the vendored `ClickException`), `typer.Exit`, `typer.Abort`, `typer.testing.CliRunner`. The two subclasses live in `cli/_typer.py` only. Floor `typer>=0.26`. |
| Usage errors exit with 2, which means "not found" here | `EnvsGroup` sets `exit_code = 1` on every `TyperException` from `make_context` / `invoke` (spike: unknown command, unknown option, missing argument → 1; an `EnvironmentStoreError` → its own code). |
| `run` needs the tokens after `--`; click swallows `--` | `PassthroughCommand.parse_args` splits before parsing (spike: `run a b -o -- python -c 1 -o` → stores `[a, b]`, overwrite, command untouched). |
| typer + `Annotated` under ty `--error-on-warning` and ruff `FBT` / `B008` | Spike passes ty and ruff with `Annotated[...]` aliases, `list[str] \| None = None` for variadic arguments and keyword-only options after `*`. `Any` appears only in the `**extra` passthrough of the two subclasses, with a comment. |
| rich markup eats `[stores…]` / `[keys]` in help; error boxes vary with width | `rich_markup_mode=None`; tests assert substrings, never full rendered help. |
| CliRunner is never a TTY and shares one input stream; typer's `prompt` / `confirm` write part of the prompt and the echo to stdout and turn Ctrl-C into `Abort` (1) | TTY-ness comes from `Runtime`; CLI tests drive prompts through `RecordingPrompter` (which also proves "no prompt"); `TerminalPrompter` avoids typer's prompt helpers and is unit-tested with fake `read_hidden` / `read_line` / `write` callables (C1). |
| Exit code 5 and failures after a commit cannot be provoked through a normal backend | `HookedAdapter` through `Runtime.adapter_opener` / `EnvironmentStore(opener=...)`. |
| Coverage of the entry point and `run` | `cli/__main__.py` is `from environment_store.cli import main` + `if __name__ == "__main__": main()` (the guard keeps `tests/unit/test_package.py`'s fresh import of every module from running the CLI). Both branches in-process: `runpy.run_module("environment_store.cli.__main__", run_name="__main__")` with patched `argv` (true) and `importlib.import_module` after removing it from `sys.modules` (false). `main()` in-process; the import guard via `sys.modules[...] = None`; `exec_process` injected with `os.execvpe` as the default reference (type-checked against `ExecProcess`, argv `list[str]`); subprocess tests prove real behaviour but are not needed for coverage. No change to coverage configuration. |
| Import layering: re-exporting the library from `environment_store/__init__.py` would load `service` / `crypto` / `config` whenever any submodule (e.g. `core`) is imported, breaking the fresh-interpreter import-direction test | Lazy `__getattr__` in the package `__init__` (PD 1). |
| `filterwarnings = ["error"]` | The library's credentials warning is asserted with `pytest.warns`; Textual / typer deprecation warnings are fixed or, if external, filtered per test with a named reason. |
| Windows | `run` falls back to `subprocess.run` + exit code, with justified suppressions because bandit (`-r src`) and ruff `S` still see the excluded branch: `import subprocess  # nosec B404 - Windows has no exec(); run's fallback only` at module top and `subprocess.run(cmd, env=env, check=False)  # noqa: S603  # nosec B603 - argv list from the user's own command line, shell=False`; `0600` modes are best effort; the project file trust check is skipped; `getpass` works; the branches are guarded by `sys.platform == "win32"` and unverified (B1: Windows is not tested in V2.0). `-k` parsing is safe for drive paths (`C:\…` has no `=`; a bare path with `=` must be written as `./a=b.key` or `store=…`). |
| Process replacement leaks open handles (SQLite WAL, file locks) | `run` closes the `EnvironmentStore` and flushes stdio before `exec_process`; tested in-process. |
| Argon2id cost in CLI tests | `Runtime.kdf_params_factory` = `CheapKdf`; exactly one library test uses the spec defaults. |
| A stray `.envstore.toml` above `tmp_path` | `project_boundary` in `Runtime`, set by the harness. |

### 6.4 Plan decisions (gaps in the spec, decided here)

Referenced in this section as *PD n*.

1. **Lazy public API.** `environment_store/__init__.py` resolves its public names through module `__getattr__`;
   type checkers see them through `if TYPE_CHECKING:` imports. Rationale: keeps `import environment_store.core`
   (and adapters) free of the library, config and crypto layers, which the existing fresh-interpreter
   import-direction test enforces, and keeps `import environment_store` cheap.
2. **Library facade owns the adapter.** `EnvironmentStore` opens one adapter in `__init__` (fail fast), wraps one
   `StoreService`, is a context manager with idempotent `close()`. Rationale: CONTRIBUTING §4 (context managers for
   resources); a refused schema (D13) or missing extra is reported at construction, not at a random later call.
3. **`KeySourceError(CryptoError)`** is added to `core/errors.py`: a key or passphrase file that is missing,
   unreadable, not UTF-8 or empty, and an empty stdin secret, exit with 4. Rationale: D24 defines 4 as "key error"
   and a missing key in non-interactive use is already 4; "the key file is missing" belongs to the same category.
4. **Existing output files and key files exit with 1** (`ValidationError`, as `write_key_file` already does).
   Exit code 3 stays reserved for stores and variables, mirroring "2 = not found (store or variable)". Exported
   files are created with mode `0600`, because they hold decrypted secrets; `--force` replaces atomically.
5. **Project `[keys]` apply to every command that needs an existing store's key**, including writing commands
   (`set`, `rm`, `import`, `rekey` old key, `cp-store` / `mv-store` source), when no `-k` is given. Keys are bound
   by store name, so this cannot redirect a write (§6.0.2 only forbids taking the *store* from the file). File keys
   for stores that are not used are ignored; a file key for a used plaintext store is an error, like `-k`.
6. **Strict project file schema:** unknown top-level keys are errors. Rationale: catches typos such as `store =`
   that would otherwise silently load nothing.
7. **Relative connection paths in the project file** (`json://`, `toml://`, `sqlite:///`) are relative to the
   project file's directory, like `[keys]`. Rationale: the file is found from any subdirectory; cwd-relative paths
   would point somewhere else in each one.
8. **Empty `ENV_STORE_*` variables count as unset.** Rationale: the common `VAR= cmd` idiom; an empty connection
   string is never valid anyway.
9. **The password warning is printed whenever the loaded project file holds a password**, even if `-c` or
   `ENV_STORE_CONNECTION` overrides it ("every command", D33): the credential sits in a possibly committed file
   regardless of which connection wins. Detected by `core.connection.connection_has_credentials`, the one detector
   shared with the PostgreSQL adapter's redaction: a URL userinfo password, or a query parameter whose
   percent-decoded name is `password` or `sslpassword`.
10. **Configuration is validated for every command, after its arguments are parsed:** `EnvsCommand.invoke` resolves
    settings before each command's callback, so a broken project file or `ENV_STORE_ORDERED_OVERWRITE` fails even
    `ls-store` or `keygen`, while `envs --help`, `envs <cmd> --help` and `--version` (handled during parsing, before
    `invoke`) always work and print no warning. Not in the root callback: typer runs it before the subcommand's
    `--help` is parsed. Rationale: one consistent place, no command that silently works with a broken
    configuration, help always available.
11. **The library one-liner prompts with `getpass`** (stderr) when stdin is a terminal, via `GetpassPrompter`, the
    only place in the library that talks to the terminal. Rationale: D36 requires "incl. prompts on a terminal";
    CONTRIBUTING §5's "no input in library code" is honoured everywhere else and the prompter is injected.
12. **`KeyInput = Path | KeyMaterial | Passphrase`; a plain `str` is refused.** A `Path` for an existing store is
    read and interpreted by the store's mode (like `-k`); a `Path` for a new secret must be a key file; passphrases
    are passed as `Passphrase`. The public `Source(name, key=...)` follows spec §7.3; core's `Source(name, secret)`
    stays internal. Rationale: a `str` could be a path or a passphrase; guessing would be a security bug.
13. **Variable output order** *(amended by D52)*: `ls`, `export`, `export-shell`, `run` and
    `Environment.variables()` / `with_sources()` list variables in store load order, each store's variables sorted
    by name, a shared variable at its first position with the merge order's value; nested output keeps the store
    load order with each store sorted. Rationale: deterministic, diff-friendly output that reads like the stores.
14. **`Environment.apply` and the one-liner do not overwrite** variables already in `os.environ` unless
    `overwrite=True`, like `run` / `export-shell` without `-o` and python-dotenv's `load_dotenv`.
15. **Dependency floors:** `typer>=0.26` (vendored click; the exception hierarchy `EnvsGroup` relies on) and
    `textual>=8.2` (the tested line). Not new dependencies, only floors of existing extras.
16. **`--version`** is added as a global option. Rationale: standard for a CLI, needs no configuration.
17. **`keygen` (and `--version`, `--help`) need no connection.** The connection is required where a store is opened
    (`CliState.open_store`); `keygen` opens none. Configuration is still validated for `keygen` (PD 10): "broken
    configuration" and "no connection configured" are different conditions. This departs from the literal D29
    wording ("every command fails"), whose stated purpose is that no data is written to a location the user did
    not choose; `keygen` writes only the path it is given. D29 was amended accordingly by the user (phase 3); the
    declined alternative would have had `keygen` call
    `get_state(ctx).settings().require_connection()` first (one line in C4, one test).
18. **Reading commands check existence before prompting and prompt once per store**, even if a store appears
    twice in the list; a wrong key is not re-prompted (exit 4).
19. **`-k` parsing:** a value is `store=path` when the text before the first `=` is a valid store name, otherwise a
    bare path (single-store shorthand only). Writing commands take a bare path or `-` only.
20. **Prompts and confirmations are written to stderr**, so `get`, `export` and `export-shell` stdout stays clean
    for `$(...)` and `eval`. `TerminalPrompter` uses `getpass` (on stderr) and a stderr prompt + stdin line
    instead of `typer.prompt` / `typer.confirm`, which write the prompt's last character and the echo to stdout.
21. **Ctrl-C exits with 130 everywhere, including at a prompt** (typer's default for an escaping
    `KeyboardInterrupt`, shell convention); `TerminalPrompter` deliberately does not catch it (typer's own prompt
    helpers would turn it into `Abort` → 1). EOF at a prompt is `typer.Abort` → 1. Both are outside the D24 table,
    which covers results of a command, not interruption; a cancelled key prompt is not a "missing key" (4).
22. **`migrate` on a file backend is an error** (exit 1): it has no schema, and a silent success would hide a wrong
    connection string.
23. **JSON shapes:** `ls-store --json` → list of `{name, encrypted, key_mode, revision, created_at, updated_at}`;
    `ls --json` → list of `{name[, value][, store]}` (keys only when `-v` / `--source`); `get --json` →
    `{name, value, store}`.
24. **`create-store` key options require `-e`**, and **`--generate-key -` is refused by every command that takes
    the option** (`create-store`, `cp-store`, `mv-store`, `rekey`, `encrypt`), in the shared C1 `new_secret`, with
    the hint "use `envs keygen -` and `-k -` / `--new-key -`". Rationale: no implicit encryption; no secret mixed
    into a command's diagnostic output; no key file literally named `-`.
25. **A value read from stdin by `set` loses exactly one trailing newline** (LF or CRLF), decided by the user as
    D38 (same rule as D3 for passphrase files): `echo secret | envs set …` stores `secret`. Bytes are decoded as
    strict UTF-8 with no other translation, so `\r` inside values and a second trailing newline survive. Values
    that must end in a newline are set with `import` (JSON/TOML/dotenv), which round-trips exactly (D28).
26. **`rm` (variables) asks no confirmation;** only `rm-store` does (spec tables list `-y` only for `rm-store`).
27. **Importing an empty document is a no-op success** (exit 0, no new revision); the service's "no variables to
    set" error is reserved for programming errors.
28. **`run` requires `--`** before the command (stores and command are otherwise ambiguous); a command that cannot
    be started exits with 127 (not found) or 126 (not executable), the shell conventions, because `run` passes
    through exit codes instead of using D24.
29. **TUI scope for V2.0:** browse stores, unlock encrypted stores, view (masked) / add / edit / delete variables.
    Store lifecycle, import / export and key lifecycle stay CLI-only. Rationale: the spec requires only that the
    TUI exists (§6.14, D15); this is the smallest useful set that exercises the library facade.
30. **Textual tests use `asyncio.run` around Pilot** instead of adding `pytest-asyncio`. Rationale: no new test
    dependency for one package.
31. **One import edge `cli → tui`, in `cli/tui_command.py` only and inside the command function.** Spec §6.14
    requires `envs tui`, and D31 says no frontend depends on another; the edge is the minimum that satisfies both:
    the CLI never imports the TUI except when `envs tui` runs, and the TUI never imports the CLI. Encoded as an
    explicit per-module exception in `tests/unit/test_import_direction.py` with tests for both directions. The
    phase 4 docs add a note to §7.1 / D31 ("`envs tui` launches the TUI").
32. **Untrusted project files are ignored.** The `.envstore.toml` found by discovery is used only if it is owned by
    the current user or root and is not world-writable; otherwise it is ignored with a warning that names the
    file and the reason, and the search stops there. Rationale: discovery walks up to `/`, so a file planted in a
    shared ancestor (e.g. `/tmp`) could otherwise redirect `connection` (secrets written to a foreign database),
    choose the stores `run` loads, or point `[keys]` at arbitrary files (the pattern of git's CVE-2022-24765).
    Group-writable files are allowed (user-private-group umasks). Skipped on Windows.
33. **A generated key file is deleted after a failure only when the store provably does not use it.** Kept (path
    printed on stderr) for any `BackendError` or non-library exception, because the write may have been
    committed (a dropped connection during `COMMIT`, a failing `delete_store(SRC)` after `mv-store` copied).
    Deleted for `ValidationError`, `ConfigurationError`, `NotFoundError`, `CryptoError`,
    `ConcurrentModificationError` and `AlreadyExistsError`, which are raised before anything is written — except
    for commands that create the target (`create-store`, `cp-store`, `mv-store`), where the file is deleted only
    if the target store does not exist when checked afterwards (`StoreExistsError` excepted: the target was
    someone else's); if that check fails, the file is kept. Rationale: deleting the only key of a committed store
    is permanent data loss; a stray key file is harmless.
34. **stdin is read as bytes and decoded as strict UTF-8, with no newline translation** (`set` values, `import`
    input, `-k -`, `--new-key -`, piped passphrases). `typer.get_text_stream` would turn `\r\n` and `\r` into
    `\n` and decode with the locale encoding. Non-UTF-8 input → `ValidationError` (exit 1); for secrets
    `KeySourceError` (exit 4, PD 3).
35. **File I/O errors of output and input files are user errors, not tracebacks.** `write_output_file` and
    `read_input_file` map every `OSError` to `BackendError` naming the path and `strerror` (exit 1), as
    `crypto.write_key_file` does, and remove a partial output or temp file on every failure, because it may hold
    decrypted secrets.

## 7. Phase 4 — outline

- **D1 · Docs, skill and release (item 16):** user documentation for the library, CLI (every command of §6.1, exit
  codes, project file, `--noinput` for CI) and TUI; a new agent skill for the V2 CLI; README; `CHANGELOG.md`
  2.0.0 section; release workflow builds and publishes with `uv build`; version `2.0.0`. Detailed when phase 3 is
  merged.
