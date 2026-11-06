# Environment Store V2 — Implementation plan

Companion to [SPEC-V2.md](SPEC-V2.md) (what to build) and [CONTRIBUTING.md](CONTRIBUTING.md) (binding engineering
rules). This document fixes **build order, module layout and the interfaces between work packages**, so that later
packages — especially the adapters, which are built in parallel — can rely on them without touching shared files.

Work happens on the branch `feature/v2`. Each work package (WP) maps to an item in the
[Environment Store V2 project](https://github.com/users/mkaufhol/projects/2).

## 1. Phases

| Phase | Work packages | Mode | Gate before the next phase |
|---|---|---|---|
| 0 | Rules and plan (this file, CONTRIBUTING.md) | — | reviewed |
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

## 3. Package layout

```
src/environment_store/
├── __init__.py              # __version__; public API grows in L1
├── py.typed
├── _toml.py                 # B1: minimal TOML writer (stdlib can only read TOML)
├── core/
│   ├── __init__.py          # re-exports of the core API
│   ├── errors.py            # B2: exception hierarchy
│   ├── validation.py        # B2: store / variable name and value rules
│   ├── models.py            # B2: StoreInfo, StoreRecord, CipherMeta, KdfParams, Source, …
│   ├── clock.py             # B2: Clock type, utc_now()
│   ├── merge.py             # B3: merge order, merge(), nested keys, bool settings
│   ├── adapter.py           # B4: Adapter / MigratableAdapter protocols
│   ├── connection.py        # B4: scheme registry, open_adapter()
│   └── service.py           # B5: StoreService (all store/variable operations)
├── crypto/
│   ├── __init__.py
│   ├── secrets.py           # B5: KeyMaterial, Passphrase (redacted repr)
│   ├── keyfile.py           # B5: key file format, generate / read / write (0600, O_EXCL)
│   ├── kdf.py               # B5: Argon2id
│   └── aead.py              # B5: payload + AAD encoding, AES-256-GCM encrypt / decrypt
├── adapters/
│   ├── __init__.py
│   ├── sql/                 # B6: shared by SQLite and PostgreSQL
│   │   ├── __init__.py
│   │   ├── schema.py        # DDL v1 per dialect, SCHEMA_VERSION, META_APP
│   │   ├── migrations.py    # migration list per dialect, pending()
│   │   ├── setup.py         # DatabaseInspection, SetupState, decide()
│   │   └── codec.py         # StoreRecord <-> row values
│   ├── files/               # A1
│   ├── sqlite/              # A2
│   └── postgres/            # A3
├── formats/                 # A4: dotenv / json / toml / posix shell
├── config/                  # L1: project file, connection resolution, secret sources
├── cli/                     # C1–C4
└── tui/                     # T1
tests/
├── conftest.py
├── support/                 # B2/B4: Hypothesis strategies, in-memory fake adapter, fake clock
├── contract/                # B4: adapter contract suite (a reusable test class)
├── unit/<mirrors src>/      # unit tests per module
└── adapters/<name>/         # A1–A3: adapter tests (contract subclass + backend specifics)
```

**Ownership rule for parallel phases:** a parallel WP only creates or edits files inside its own directories
(`src/environment_store/<its package>/`, `tests/adapters/<its name>/` or `tests/unit/<its package>/`). Shared files
(`pyproject.toml`, `uv.lock`, CI, `core/`, `adapters/sql/`, `tests/support/`, `tests/contract/`) are prepared in
phase 1. If a parallel WP finds a defect in a shared file, it reports it instead of editing it.

## 4. Phase 1 — Base

### B1 · Project skeleton (item 01)

- Delete all V1 code, tests, docs (keep `docs/assets/`), `tox.ini` and the V1 agent skill
  (`.claude/skills/environment-store-cli/`). Replace `README.md` with a short V2 placeholder linking to the spec.
  Add an `Unreleased — 2.0.0` section to `CHANGELOG.md`.
- `pyproject.toml`:
  - `version = "2.0.0.dev0"`, `requires-python = ">=3.13"`, classifiers 3.13–3.15, keywords updated.
  - `dependencies = ["cryptography>=44"]` (D6, D34).
  - extras: `postgres = ["psycopg[binary]>=3.2"]`, `cli = ["typer>=0.15"]`, `tui = ["textual>=3"]`,
    `all = [...]`. Entry points `environment-store` and `envs` are added in C1, not now.
  - dependency groups: `dev` (ruff, ty, pre-commit, bandit), `testing` (pytest, coverage, hypothesis,
    `psycopg[binary]`). Default groups: both.
  - ruff: `target-version = "py313"`, `line-length = 100`, a strict rule selection including at least
    `E W F I N UP B A C4 SIM RET PTH PL RUF ANN S PT TID TC ERA PERF FBT EM TRY D`, `pydocstyle.convention =
    "google"`; tests may ignore `S101`, `D`, `PLR2004`. No other blanket ignores without a comment.
  - ty: `python-version = "3.13"`; CI and pre-commit run `ty check --error-on-warning`.
  - pytest: `addopts = "-ra --strict-markers --strict-config"`, `xfail_strict = true`,
    `filterwarnings = ["error"]`, `testpaths = ["tests"]`, marker `postgres`.
  - coverage: `branch = true`, `source = ["environment_store"]`, `fail_under = 100`, `show_missing = true`,
    `exclude_also` for `if TYPE_CHECKING:`, `\.\.\.$` protocol bodies, `raise NotImplementedError`,
    `if sys.platform == "win32":`.
  - bandit: `exclude_dirs = ["tests"]`.
- `.pre-commit-config.yaml`: current hook versions; ruff check + format, uv-lock, ty (`--error-on-warning`),
  bandit.
- CI (`.github/workflows/ci.yml`): lint job (format check, ruff, ty, bandit); test matrix 3.13 / 3.14 / 3.15 with
  `uv run --python X coverage run -m pytest` + `coverage report`; PostgreSQL binaries on `PATH` for A3
  (`echo "$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)" >> "$GITHUB_PATH"`); build job.
  `release.yml` stays as is.
- `src/environment_store/__init__.py` (`__version__` via `importlib.metadata`), `py.typed`.
- `_toml.py`: `dumps(document: Mapping[str, TomlValue]) -> str` for the subset V2 needs: `str`, `int`, `bool`,
  aware `datetime`; nested mappings at top level become `[table]`s, deeper mappings inline tables; keys bare when
  they match `[A-Za-z0-9_-]+`, quoted otherwise; strings as basic strings with full TOML escaping. Property test:
  `tomllib.loads(dumps(x)) == x` for generated documents.
- One smoke test for `__version__` so the suite is green at 100 %.

### B2 · Domain model and validation (item 02)

- `core/errors.py` — hierarchy (category base classes are what C1 maps to exit codes, D24):

  | Base class (exit code) | Concrete errors |
  |---|---|
  | `EnvironmentStoreError` (1) | root |
  | `ValidationError(EnvironmentStoreError, ValueError)` (1) | invalid names, values, connection strings, arguments; `AlreadyEncryptedError`, `NotEncryptedError`, `PlaintextNotAllowedError` |
  | `ConfigurationError` (1) | no connection configured (D29), bad env values, project file problems |
  | `MissingExtraError` (1) | optional dependency not installed (`extra: str` attribute) |
  | `NotFoundError` (2) | `StoreNotFoundError`, `VariableNotFoundError` (`names: tuple[str, ...]`) |
  | `AlreadyExistsError` (3) | `StoreExistsError`, `VariableExistsError` (`names: tuple[str, ...]`) |
  | `CryptoError` (4) | `KeyRequiredError`, `DecryptionError`, `InvalidKeyFileError`, `KeyModeMismatchError` |
  | `ConcurrentModificationError` (5) | — |
  | `BackendError` (1) | `DatabaseNotCleanError`, `SchemaOutdatedError`, `SchemaTooNewError` |

- `core/validation.py`: `validate_store_name` (D27 regex), `validate_variable_name` (`^[A-Za-z_][A-Za-z0-9_]*$`),
  `validate_value` (any `str` without `\x00`, D28), `validate_variables(Mapping[str, str])`. Each raises
  `ValidationError` naming the offending item but **never echoing a value** (it may be a secret).
- `core/models.py` (all `frozen=True, slots=True, kw_only=True`):
  - `Cipher(StrEnum)`: `AES256GCM = "aes256gcm"`; `KeyMode(StrEnum)`: `KEYFILE`, `PASSPHRASE`.
  - `KdfParams`: `name: Literal["argon2id"]`, `iterations: int = 3`, `memory_kib: int = 65536`, `lanes: int = 4`,
    `salt: bytes` (16 bytes) (D34); `to_json()` / `from_json()` using the spec keys `name, t, m, p, salt`
    (salt base64).
  - `CipherMeta`: `cipher: Cipher`, `mode: KeyMode`, `kdf: KdfParams | None` (required iff passphrase);
    `to_json()` / `from_json()` → `{"cipher", "mode", "kdf"?}`.
  - `StoreInfo`: `name`, `encrypted: bool`, `revision: int`, `created_at`, `updated_at`.
  - `StoreRecord`: `name`, `revision: int` (≥ 1), `created_at`, `updated_at` (aware, `created_at <= updated_at`),
    and **exactly one** of `variables: Mapping[str, str]` (stored as an immutable copy) or `ciphertext: bytes` +
    `cipher_meta: CipherMeta`. Properties `encrypted`, `info`. Constructors `StoreRecord.plain(...)`,
    `StoreRecord.sealed(...)`. Invariants validated in `__post_init__`.
  - `Source`: `name: str`, `secret: Secret | None` (repr redacted) — one entry of a load list.
  - `PAYLOAD_FORMAT_VERSION = 1`.
- `core/clock.py`: `type Clock = Callable[[], datetime]`, `utc_now()`.
- `tests/support/strategies.py`: Hypothesis strategies `store_names()`, `variable_names()`, `values()` (incl. empty,
  multi-line, unicode, quotes, `$`, `=`, leading/trailing whitespace; never NUL), `variable_maps()`,
  `plain_records()`, `sealed_records()`. `tests/support/clock.py`: deterministic fake clock.

### B3 · Merge logic (item 03)

- `core/merge.py`:
  - `MergeOrder(StrEnum)`: `LAST_WINS`, `FIRST_WINS`.
  - `merge(stores: Sequence[tuple[str, Mapping[str, str]]], *, order: MergeOrder = LAST_WINS) -> dict[str, str]`.
  - `merge_with_sources(...) -> dict[str, tuple[str, str]]` (value + winning store, for `ls --source`).
  - `nested(stores) -> dict[str, dict[str, str]]` (store → variables, for JSON/TOML `--nested`).
  - `nested_flat_key(store: str, variable: str) -> str` → `STORE__VAR` in SCREAMING_SNAKE_CASE (`-` → `_`,
    D30) and `nested_flat(stores) -> dict[str, str]` raising `ValidationError` on a collision.
  - `parse_bool_setting(raw: str, *, setting: str) -> bool` (`true/false/1/0/yes/no`, case-insensitive; anything
    else raises `ConfigurationError`).
  - `order_from_setting(ordered_overwrite: bool) -> MergeOrder`.

### B4 · Adapter contract, connection registry, contract suite (item 04)

- `core/adapter.py`:

  ```python
  class Adapter(Protocol):
      def list_stores(self) -> list[StoreInfo]: ...  # sorted by name
      def create_store(
          self, record: StoreRecord
      ) -> None: ...  # record.revision == 1; StoreExistsError
      def read_store(self, name: str) -> StoreRecord: ...  # StoreNotFoundError
      def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
          ...
          # stored revision must equal expected_revision, else ConcurrentModificationError (D7);
          # record.revision must be expected_revision + 1, else ValidationError; StoreNotFoundError

      def delete_store(self, name: str) -> None: ...  # StoreNotFoundError
      def close(self) -> None: ...
      def __enter__(self) -> Self: ...
      def __exit__(self, *exc: object) -> None: ...


  class MigratableAdapter(Adapter, Protocol):
      def migrate(self) -> MigrationReport: ...  # SQL adapters only (D11)
  ```

  `MigrationReport`: `from_version: int | None`, `to_version: int`, `created: bool`.
- `core/connection.py`:
  - `scheme_of(url: str) -> str` (lowercased; `ValidationError` for strings without `scheme://`).
  - `ADAPTER_FACTORIES: Mapping[str, str]` — scheme → `"module:function"`, **pre-registered for all V2 schemes**
    so parallel adapter WPs never edit this file:
    `json` → `environment_store.adapters.files:open_json`, `toml` → `environment_store.adapters.files:open_toml`,
    `sqlite` → `environment_store.adapters.sqlite:open_sqlite`, `postgresql` and `postgres` →
    `environment_store.adapters.postgres:open_postgres`. Each factory has the signature
    `(url: str) -> Adapter` and parses its own URL.
  - `open_adapter(url: str, *, factories: Mapping[str, str] = ADAPTER_FACTORIES) -> Adapter` — unknown scheme →
    `ValidationError` listing the supported schemes; `ImportError` of an optional dependency → `MissingExtraError`.
- `tests/support/memory_adapter.py`: `MemoryAdapter`, an in-memory reference implementation (used by core tests and
  as the contract suite's own reference).
- `tests/contract/adapter_contract.py`: `class AdapterContract` — a test class with an abstract `adapter` fixture.
  Each adapter test module subclasses it (`class TestJsonAdapter(AdapterContract): ...`) and provides the fixture,
  plus a `reopen` fixture (a second adapter instance on the same backend, for persistence and concurrency tests).
  The suite covers: empty listing; create / read round-trip for plain and sealed records (Hypothesis: arbitrary
  names, values and binary ciphertexts); duplicate create; listing sorted with correct `StoreInfo`; write with
  correct revision; stale revision → `ConcurrentModificationError` and nothing written; wrong record revision;
  write / read / delete of a missing store; delete then re-create; persistence across `reopen`; two instances
  racing on the same revision → exactly one wins; timestamps preserved (aware UTC, microsecond precision);
  context manager closes.
- `MemoryAdapter` passes `AdapterContract`.

### B5 · Encryption and store service (item 05)

- `crypto/secrets.py`: `KeyMaterial(key: bytes)` (exactly 32 bytes) and `Passphrase(text: str)` (non-empty), both
  with a redacted `repr`/`str`; `type Secret = KeyMaterial | Passphrase`.
- `crypto/keyfile.py`: format `envstore-key-v1:<urlsafe base64 of 32 bytes, no padding>` + `\n`;
  `generate_key() -> KeyMaterial` (`secrets.token_bytes`), `format_key`, `parse_key(text) -> KeyMaterial`
  (`InvalidKeyFileError`), `read_key_file(path)`, `write_key_file(path, key)` (`O_CREAT | O_EXCL`, mode `0600`,
  refuses to overwrite → `ValidationError`), `read_passphrase_file(path)` (strips one trailing newline, D3).
- `crypto/kdf.py`: `new_kdf_params() -> KdfParams` (random salt, D34 defaults), `derive_key(passphrase, params) ->
  KeyMaterial` via `cryptography`'s Argon2id.
- `crypto/aead.py`:
  - plaintext payload = canonical JSON (`sort_keys=True`, `separators=(",", ":")`, UTF-8) of
    `{"variables": {...}}`;
  - AAD = canonical JSON of `{"store": name, "format": PAYLOAD_FORMAT_VERSION, "cipher": meta.to_json()}` (D5);
  - `seal(variables, *, store, meta, key) -> bytes` → `nonce (12 random bytes) || AESGCM ciphertext+tag`;
  - `open_sealed(ciphertext, *, store, meta, key) -> dict[str, str]` → `DecryptionError` on any failure (wrong
    key, tampering, other store name, changed metadata, malformed payload), never leaking details.
- `core/service.py` — `StoreService(adapter, *, clock=utc_now, kdf_params_factory=new_kdf_params)`; the single
  implementation of all operations used by L1 and the CLI:
  - `list_stores()`, `create_store(name, *, secret: Secret | None = None) -> StoreInfo`, `delete_store(name)`;
  - `read_variables(name, *, secret=None) -> dict[str, str]`;
  - `set_variables(name, values, *, secret=None, overwrite=False)` — conflicts → `VariableExistsError` listing
    all conflicting names, nothing written (D18);
  - `delete_variables(name, names, *, secret=None)` — missing → `VariableNotFoundError`, nothing written;
  - `encrypt_store(name, *, secret)` (D4; `AlreadyEncryptedError`), `rekey_store(name, *, old, new)` (new salt,
    may switch mode; `NotEncryptedError`);
  - `copy_store(src, dst, *, secret=None, encryption: Literal["same", "plain"] | Secret = "same",
    destination: StoreService | None = None)` and `move_store(...)` (copy, then delete the source; a failure never
    leaves zero copies) — re-encrypts because of D5;
  - `load(sources: Sequence[Source]) -> list[tuple[str, dict[str, str]]]` in source order.
  - Encrypted store without a secret → `KeyRequiredError`; secret type not matching the store's mode →
    `KeyModeMismatchError`; every write is read → modify → seal with a fresh nonce → `write_store(...,
    expected_revision=...)` with `updated_at = clock()`.
- Argon2id is slow by design: tests inject cheap `KdfParams` through `kdf_params_factory`, and exactly one test
  asserts the spec defaults.

### B6 · SQL common (shared part of items 07/08)

- `adapters/sql/schema.py`: `SCHEMA_VERSION = 1`, `META_APP = "environment-store"`; DDL v1 (D12) as statement
  tuples: `SQLITE_SCHEMA_V1` and `POSTGRES_SCHEMA_V1` (the latter with a `{schema}` placeholder that A3 composes
  with `psycopg.sql.Identifier`); including the `meta` rows.
- `adapters/sql/migrations.py`: `Migration(version: int, statements: tuple[str, ...])`, `SQLITE_MIGRATIONS`,
  `POSTGRES_MIGRATIONS`, `pending(migrations, current: int | None) -> list[Migration]`.
- `adapters/sql/setup.py` (pure, D11/D13): `DatabaseInspection(tables: frozenset[str], meta: Mapping[str, str] |
  None)`; `SetupState(StrEnum)`: `EMPTY`, `CURRENT`, `OUTDATED`, `NEWER`, `FOREIGN`; `classify(inspection) ->
  SetupState`; `SetupAction(StrEnum)`: `CREATE`, `USE`, `UPGRADE`; `decide(state, *, auto_upgrade: bool) ->
  SetupAction` raising `DatabaseNotCleanError` (FOREIGN), `SchemaTooNewError` (NEWER) and `SchemaOutdatedError`
  (OUTDATED without auto-upgrade, hint: run `environment-store migrate`).
- `adapters/sql/codec.py`: `record_to_row(record, *, dialect)` / `row_to_record(row, *, dialect)` —
  JSON (de)serialization of `variables` and `cipher_meta`; SQLite timestamps as ISO 8601 UTC text, PostgreSQL as
  `datetime`; `encrypted` derived from the record.

## 5. Phase 2 — Adapters and formats (parallel)

Each WP runs in its own worktree on branch `v2/<wp>` created from `feature/v2` after phase 1, and only touches its
own directories (§3).

### A1 · JSON and TOML file adapters (item 06)

`adapters/files/`: `open_json(url)`, `open_toml(url)`, one `FileAdapter` parameterised by a `FileFormat`
(serializer pair). URL → directory (`json://rel`, `json:///abs`, `json://~/dir`); directory created on first write.
One file per store, store name = file stem; other extensions ignored. File layout per spec §3.2 (`format`,
`encrypted`, `revision`, `created_at`, `updated_at`, `variables` | `payload` + `[cipher]`). Writes: per-store lock
(`fcntl.flock` on POSIX; `msvcrt.locking` behind `sys.platform == "win32"`), revision check under the lock, temp
file in the same directory, `os.replace`. TOML via `tomllib` + `environment_store._toml.dumps`. Corrupt or foreign
files → `BackendError` naming the file. Tests: contract suite for both formats, layout snapshots, atomicity
(temp files cleaned up on failure), concurrent writers via two processes.

### A2 · SQLite adapter (item 07)

`adapters/sqlite/`: `open_sqlite(url)` (`sqlite:///relative.db`, `sqlite:////absolute.db`); stdlib `sqlite3`,
`PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout`. On open: inspect (`sqlite_master`, `meta`) →
`classify` → `decide(auto_upgrade=True)` → create / upgrade / use; refused states raise the B6 errors and change
nothing. `write_store` as one `UPDATE … WHERE name = ? AND revision = ?` (0 rows → conflict or not found).
`migrate()` implemented. Tests: contract suite, every setup state, check constraint enforcement, two connections
racing.

### A3 · PostgreSQL adapter (item 08)

`adapters/postgres/`: `open_postgres(url)`; `?schema=` (default `environment_store`, regex
`^[a-z_][a-z0-9_]{0,62}$`) removed from the URL before `psycopg.connect`; lazy `psycopg` import →
`MissingExtraError("postgres")`. On open: inspect the schema → `classify` → `decide(auto_upgrade=False)`; empty →
`CREATE SCHEMA` + v1 in one transaction; missing privilege → `BackendError` with the `migrate` hint. All SQL
composed with `psycopg.sql`; JSONB / BYTEA / TIMESTAMPTZ. `migrate()` creates or upgrades. Tests run against a
throwaway cluster: a session fixture uses `ENV_STORE_TEST_POSTGRES_URL` if set, otherwise starts a temporary
cluster with `initdb` / `pg_ctl` from `PATH` (unix socket in a temp dir, random port, trust auth) and stops it
afterwards; each test gets a fresh database. If neither is available the tests **fail** with a hint (never skip
silently). Tests: contract suite, schema isolation (`?schema=a` vs `?schema=b` in one database), foreign
schema refused, outdated schema refused until `migrate()`, identifier injection attempts rejected.

### A4 · Formats (item 09)

`formats/`: `dotenv.dumps(mapping) -> str` (quote only when needed; escape `\n`, `"`, `\\`, `$`; compatible with
python-dotenv and Docker Compose) and `dotenv.loads(text) -> dict[str, str]`; `json_format` / `toml_format`
`dumps` / `loads` for flat (`dict[str, str]`) and nested (`dict[str, dict[str, str]]`) documents — `loads` accepts
only flat objects of strings (D33); `shell.posix_exports(mapping, *, overwrite: bool) -> str` using
`shlex.quote` and `[ -z "${VAR+x}" ] && export VAR=…` without overwrite (D23); `infer_format(path) ->
FileFormat | None` (D22). Property tests: `loads(dumps(x)) == x` for every format; shell output evaluated by
`/bin/sh -c` in a test reproduces the values exactly.

## 6. Phase 3 and 4 — outline

- **L1 · Library and project file (item 10):** `config/` — `.envstore.toml` discovery (cwd upwards), schema
  validation, precedence resolution (CLI > env > project file > default) for connection and merge order, password
  warning (D25); secret sources (file, stdin, prompt via an injected `Prompter`, `--noinput`). Public API in
  `environment_store/__init__.py`: `EnvironmentStore`, `Source`, `load(*stores)` (D36), errors.
- **C1 · CLI foundation (item 11):** typer app, entry points `environment-store` and `envs`, global options,
  positional store lists with `-k store=path`, exit-code mapping from the error categories, `--json`.
- **C2–C4 (items 12–14):** command groups, built in parallel once C1 is merged (one module per group).
- **T1 · TUI (item 15)**, **D1 · docs and release (item 16)**.
