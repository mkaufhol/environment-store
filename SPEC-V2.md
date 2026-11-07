# Environment Store V2 — Specification

**Status:** Refined. All questions and proposals are decided (D1–D53). Ready for implementation planning.
**Scope:** Complete rebuild. No backward compatibility with V1 (0.1.x).

> **How to read this document**
> - Plain text is taken from the original notes (translated and structured).
> - Headings or items marked **decided (D*n*)** have been settled in refinement; see the [Decision log](#12-decision-log).

---

## 1. Goals and principles

Environment Store is a centralized, persistent store for environment variables. V2 replaces the hierarchical model of
V1 (organisation → project → environment → service) with a flat set of independent **stores** (packages) that are
combined at load time.

Key facts:

1. **No hierarchy, but stores (packages).** A store is a named, flat collection of variables. Stores do not nest and
   do not reference each other.
2. **SQL is the main storage.** PostgreSQL and SQLite are first-class backends.
3. **Local JSON and TOML files** are supported as a lightweight backend.
4. **Stores can be encrypted or unencrypted.** Reading the contents of an encrypted store requires its decryption key.
5. **Core** contains the storage logic and the store/retrieve functionality. Nothing else.
6. **Extras:** Python library, CLI, API, TUI, web interface. Extras use the core and build on each other.
7. **No running process.** Everything is called on demand. A long-running process exists only when the API or web
   interface extra is deployed.
8. **Order matters.** When several stores are loaded, the store loaded last overwrites variables of earlier stores,
   unless configured otherwise (see [`ENV_STORE_ORDERED_OVERWRITE`](#52-env_store_ordered_overwrite)).
9. **Lean and light.** Minimal dependencies in the core; every backend and frontend is an optional extra.

**Terminology** *(decided, D26)*: the named collection of variables is called a **store** everywhere (code, CLI,
docs). Where the storage location is meant, the docs say **backend**.

---

## 2. Domain model

### 2.1 Store

| Field | Description |
|---|---|
| `name` | Unique identifier within a backend. |
| `encrypted` | Whether the store's contents are encrypted. Can be switched on later with `encrypt`, never off (see [§4.5](#45-key-lifecycle-commands-decided-d4)). |
| `variables` | Mapping of variable name → value. |

**Naming and values** *(decided, D27, D28)*

| Item | Rule |
|---|---|
| Store name | `^[a-z][a-z0-9_-]{0,62}$`: lowercase letters, digits, `_`, `-`, starting with a letter. Lowercase only, because store names become file names and macOS/Windows file systems are case-insensitive. **Shell compatible** *(amended, D40)*: the store name cast to SCREAMING_SNAKE_CASE (upper-cased, `-` → `_`; `customer-a` → `CUSTOMER_A`) must be a valid POSIX shell variable name (`^[A-Z_][A-Z0-9_]*$`). The regex guarantees this, so every nested key `STORE__VAR` is a valid variable name for `--nested` dotenv export, `export-shell`, `run` and import. Any future change to the store name rule must keep this property. |
| Value | Any UTF-8 string: empty strings and multi-line values (certificates, keys) are allowed; only NUL is forbidden, because environment variables can't hold it. Values round-trip exactly. Strings only, no typed values; JSON/TOML exports write strings. |

> *(decided, D33)* variable names follow `^[A-Za-z_][A-Za-z0-9_]*$` (portable POSIX env var name) and are
> case-sensitive.

> **metadata** *(decided, D33)* — every store additionally keeps `created_at`, `updated_at` and, if encrypted, the cipher
> identifier and its parameters (see [§4](#4-encryption)). No descriptions, tags or owners in V2.0.

### 2.2 Load order and merge semantics

Loading means reading one or more stores in a given order and merging them into a single result.

- `ordered_overwrite = true` (default): **last wins.** A variable present in several stores takes the value of the
  last store that contains it.
- `ordered_overwrite = false`: **first wins.** A variable that is already set is not overwritten by later stores.
- **Output order** *(D52)*: merged output lists the stores' variables in load order. Within one store they are
  sorted by name (code point order); a variable that appears in several stores keeps the position of its **first**
  appearance and takes the value chosen by the merge order. Example: `store-a` = `ENV`, `DEBUG`; `store-b` = `ENV`,
  `DB_NAME`; `export store-a store-b` → `DEBUG=True`, `ENV=staging`, `DB_NAME=test`. This applies to every merged
  output: `ls` (also `--json`), `export` (every format), `export-shell`, `run` and the library's merged results.
- **Nested mode** (`--nested`): no merging at all. Each store keeps its own namespace (see [§6.11](#611-export-stores)).

> *(decided, D33)* merging is a pure core function (`merge(stores, ordered_overwrite) -> dict[str, str]`) so that every
> extra (library, CLI, API) behaves identically.

---

## 3. Storage backends (adapters)

An adapter defines where data is stored. The adapter is selected via the connection string
([`ENV_STORE_CONNECTION`](#51-env_store_connection)).

| Adapter | Priority | Connection string |
|---|---|---|
| JSON files | **MUST** | `json://path/to/directory` *(D9)* |
| TOML files | **MUST** | `toml://path/to/directory` *(D9)* |
| PostgreSQL | **MUST** | `postgresql://user:pass@host:5432/db` |
| SQLite | **MUST** | `sqlite:///relative.db`, `sqlite:////absolute/path.db` |
| AWS S3 | TBD | e.g. `s3://bucket/prefix` |
| AWS SSM Parameter Store | TBD | e.g. `ssm://prefix?region=eu-central-1` |
| AWS Secrets Manager | TBD | e.g. `secretsmanager://prefix?region=…` — one secret per store |

### 3.1 Adapter contract

> *(decided, D33)* the adapter is deliberately dumb. It stores and returns **opaque store records**; it knows nothing
> about encryption, merging or export formats. This keeps adapters tiny and makes encrypted and unencrypted stores
> identical from the adapter's point of view.
>
> ```python
> class Adapter(Protocol):
>     def list_stores(self) -> list[StoreInfo]: ...          # name, encrypted, timestamps
>     def create_store(self, record: StoreRecord) -> None: ...  # raises StoreExistsError
>     def read_store(self, name: str) -> StoreRecord: ...        # raises StoreNotFoundError
>     def write_store(self, record: StoreRecord, expected_revision: int) -> None: ...
>         # full replace, atomic; raises ConcurrentModificationError (D7)
>     def delete_store(self, name: str) -> None: ...             # raises StoreNotFoundError
> ```
>
> `StoreRecord` holds the metadata and `revision` plus either plaintext `variables` (unencrypted) or a `ciphertext` payload
> (encrypted). Each adapter serializes the record in its own way (see §3.2, §3.3). Variable-level operations (`get`,
> `set`, `rm`) are implemented once in the core on top of read-modify-write.
>
> A shared contract test suite runs against every adapter (as in V1, but smaller).

### 3.2 File adapters (JSON, TOML) *(decided, D9)*

JSON and TOML are two adapters with their own connection schemes. They share one implementation and differ only in
serialization.

- `json://path/to/directory` → one `<store-name>.json` file per store in that directory.
- `toml://path/to/directory` → one `<store-name>.toml` file per store in that directory.
- Files with the other extension in the same directory are ignored.
- This replaces the `local://` convention from the original notes.

> *(decided, D33)*
> - Path resolution mirrors SQLite: `json://relative/dir`, `json:///absolute/dir`, `json://~/dir` expands `~`.
>   The directory is created on first write.
> - *(decided, D43)* The same path rules hold for all three file-based backends: `json://`, `toml://` and
>   `sqlite:///` expand a leading `~` and create a missing directory (the store directory, or the SQLite file's
>   parent directory) on first write with mode `0700`; store files and the SQLite database (with its `-wal` /
>   `-shm` files) are created with mode `0600`.
> - Writes are atomic (write to temp file, `os.replace`), guarded by a per-store lock and the revision check (D7).
>   Locking via `fcntl.flock` on POSIX and `msvcrt.locking` on Windows.
> - The store name is the file name. It is not repeated inside the file.
> - Reading TOML uses the stdlib `tomllib`. The stdlib can't write TOML, so the adapter has its own small writer for
>   this fixed, flat structure. This keeps D6 (no dependency besides `cryptography`).
> - File layout, plaintext and encrypted:
>
> ```json
> {
>   "format": 1,
>   "encrypted": false,
>   "revision": 3,
>   "created_at": "2026-11-06T10:00:00Z",
>   "updated_at": "2026-11-06T12:30:00Z",
>   "variables": { "DB_HOST": "localhost", "DB_PORT": "5432" }
> }
> ```
>
> ```toml
> format = 1
> encrypted = true
> revision = 7
> created_at = 2026-11-06T10:00:00Z
> updated_at = 2026-11-06T12:30:00Z
> payload = "base64(nonce || ciphertext)"
>
> [cipher]
> name = "aes256gcm"
> mode = "passphrase"
> kdf = { name = "argon2id", t = 3, m = 65536, p = 4, salt = "base64…" }
> ```

### 3.3 SQL adapters (PostgreSQL, SQLite)

**Data model** *(decided, D8)*: one row per store in a single `stores` table. The variables are stored as one payload
per store: a JSON object for plaintext stores, ciphertext for encrypted ones. There is no per-variable table.

**Libraries** *(decided, D10)*: SQLite through the stdlib `sqlite3` module (no dependency). PostgreSQL through
`psycopg` 3 (the `postgres` extra). Schema migrations through a small built-in migration runner. No ORM, no
SQLAlchemy, no external migration tool.

### 3.3.1 Initial schema (version 1) *(decided, D12)*

Identical for both dialects. On SQLite, `JSONB` becomes `TEXT` (JSON), `BYTEA` becomes `BLOB` and `TIMESTAMPTZ`
becomes `TEXT` (ISO 8601, UTC). On PostgreSQL both tables live in the dedicated schema (see §3.3.2).

```sql
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- initial rows: ('app', 'environment-store'), ('schema_version', '1')

CREATE TABLE stores (
    name        TEXT PRIMARY KEY,
    encrypted   BOOLEAN NOT NULL,
    cipher_meta JSONB,              -- encrypted only: cipher, mode, kdf params
    variables   JSONB,              -- plaintext only: {"NAME": "value", ...}
    ciphertext  BYTEA,              -- encrypted only: nonce || ciphertext
    revision    INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    CHECK (
        (encrypted AND cipher_meta IS NOT NULL AND ciphertext IS NOT NULL AND variables IS NULL)
        OR
        (NOT encrypted AND cipher_meta IS NULL AND variables IS NOT NULL AND ciphertext IS NULL)
    )
);
```

- `meta` marks the database (or Postgres schema) as ours and holds the schema version. The row
  `('app', 'environment-store')` is how the tool recognises its own schema.
- The check constraint guarantees that a store is either plaintext or encrypted, never both or neither.
- Splitting `variables` and `ciphertext` keeps plaintext queryable with SQL JSON functions and stores ciphertext as
  binary.
- Store name rules (Q2) are validated in the core, not in the database.

### 3.3.2 Isolation and first setup *(decided, D11, D13)*

**PostgreSQL** uses its own schema:

- All tables live in a dedicated Postgres schema, default `environment_store`. Other content of the database is
  never touched, so a shared database works.
- The schema name is configurable with `?schema=<name>` on the connection string, e.g.
  `postgresql://user@host/app_db?schema=team_a`. The parameter is removed before the string is passed to psycopg.
  Several independent environment stores can share one database this way.
- Schema name rule: `^[a-z_][a-z0-9_]{0,62}$`. It is always quoted as an identifier, never interpolated as text.

**SQLite** has no schemas. The file is clean only if it doesn't exist yet (it is created) or contains no tables.

**What happens on connect**

| State found | SQLite | PostgreSQL |
|---|---|---|
| Missing / empty (SQLite: no file or no tables; PG: no schema or empty schema) | Create schema v1; a missing file is created on the first write, reads create nothing (D43) | Create schema (if needed) and tables v1 |
| Ours (`meta.app = environment-store`), same version | Use it | Use it |
| Ours, older version | Upgrade automatically | Refuse; hint to run `migrate` |
| Ours, newer version than the client | Refuse; hint to upgrade environment-store | Same |
| Not empty and not ours (foreign tables, or no valid `meta`) | Warn and refuse; nothing is created or changed | Same |

- "Refuse" means the command fails with a clear message and exit code `1`; nothing is written.
- `migrate` is a V2.0 command. It upgrades an existing schema of ours and can also be used for the first setup
  (e.g. by an admin, when the regular database user has no `CREATE` privilege).

> *(decided, D33)* on PostgreSQL, a missing `CREATE` privilege during automatic first setup fails with a hint that an
> admin can run `environment-store migrate` once with a privileged user.

### 3.4 AWS adapters (TBD)

Not part of V2.0. Notes for later:

- **S3:** one object per store (`<prefix>/<store>.json`).
- **Parameter Store:** one parameter per store (size limits: 4 KB standard / 8 KB advanced) or one per variable.
- **Secrets Manager:** one secret per store.

---

## 4. Encryption

Encrypted stores require the decryption key for **every** operation on their contents (read and write).

### 4.1 What is encrypted *(decided, D1)*

The **whole store payload** is encrypted as one blob: all variable names and values together, serialized as JSON.
Only the store name and metadata (encryption flag, cipher, KDF parameters, timestamps) remain visible.

- No variable names leak. Without the key, nobody can tell which variables a store contains or how many.
- Adapters stay trivial: an encrypted store is an opaque payload, the same for files, SQL and later S3 / Secrets
  Manager.
- Every write is decrypt → modify → re-encrypt. For the expected store sizes this doesn't matter.
- Consequence: `ls` (names only) also needs the key. `ls-store` shows that a store is encrypted, but no variable
  count.

### 4.2 Cipher *(decided, D2)*

V2.0 ships a single cipher, **AES-256-GCM**, in two key modes:

| Mode | Secret | Key derivation | Metadata stored with the store |
|---|---|---|---|
| `keyfile` | Random 256-bit key in a key file | none | `{cipher: "aes256gcm", mode: "keyfile"}` |
| `passphrase` | Human passphrase | Argon2id (`cryptography` ≥ 44, D34) | `{cipher: "aes256gcm", mode: "passphrase", kdf: {name: "argon2id", t, m, p, salt}}` |

- The cipher ID and mode are stored per store, so more ciphers (e.g. age for multi-recipient team stores) can be
  added later without migrating existing stores.
- A wrong key or passphrase fails with a clear `DecryptionError` (CLI exit code `4`), never with garbage output. GCM
  authentication guarantees this.

> **Cipher details** *(decided, D33, D34)*
> - Fresh random 96-bit nonce on every write. The nonce is stored together with the ciphertext.
> - Passphrases are stretched with **Argon2id** (D34), parameters per RFC 9106 (second recommended option):
>   `t=3` iterations, `m=64 MiB`, `p=4` lanes, 16-byte random salt, 32-byte output. The parameters are stored with
>   the store, so they can be raised later without breaking existing stores. The salt stays the same until
>   `rekey`. Requires `cryptography` ≥ 44.
> - Key file format: one line of text, `envstore-key-v1:<base64url of 32 bytes>`. The prefix lets the tool reject a
>   file that isn't a key file (e.g. a passphrase file passed to a `keyfile` store) with a clear error.

**Associated data** *(decided, D5)*: the authenticated data (AAD) of every encryption is store name + payload format
version + cipher metadata. A ciphertext is therefore bound to its store: copying one store's payload into another
store, or changing the cipher metadata, makes decryption fail. Consequence: renaming an encrypted store re-encrypts
it and needs its key.

**Dependency** *(decided, D6)*: `cryptography` (for AES-GCM) is a required dependency of the core package and its only
third-party dependency. `pip install environment-store` always supports encryption.

### 4.3 Supplying the key *(decided, D3)*

| Source | Syntax | Notes |
|---|---|---|
| Key file | `-k ./a.key` | Default. For `keyfile` stores the file holds the key. For `passphrase` stores it holds the passphrase (one trailing newline is stripped). |
| Stdin | `-k -` | Reads the key or passphrase from stdin, e.g. `op read … \| envs ls a -k -`. Only one `-k -` per command. |
| Environment variable *(D53)* | `ENV_STORE_KEY_<STORE>` | Key text (`envstore-key-v1:…`) for `keyfile` stores, the passphrase for `passphrase` stores; one trailing newline is stripped. For deployments (Heroku config vars, Kubernetes Secrets) where no key file can be shipped. |
| Interactive prompt | *(no `-k`)* | If a store is encrypted, no `-k` is given and stdin is a terminal, the CLI asks with a hidden prompt. Never triggered in non-interactive use. That case fails with exit code `4`. |

- No literal keys as CLI arguments (they would end up in shell history and `ps`).
- *(Amended by D53, was: no environment variables for keys.)* **Key from the environment:** an existing encrypted
  store's key or passphrase may come from `ENV_STORE_KEY_<STORE>`, where `<STORE>` is the store name in
  SCREAMING_SNAKE_CASE (`-` → `_`, always a valid variable name by D40), e.g. `ENV_STORE_KEY_PROD`,
  `ENV_STORE_KEY_CUSTOMER_A`.
  - Precedence: `-k` / library `key=` / `keys=` / `Source(key=…)` > `ENV_STORE_KEY_<STORE>` > project file `[keys]` >
    hidden prompt (never with `--noinput`). It applies wherever an existing store's key is needed: CLI, library
    (`EnvironmentStore` methods and `load`), the one-liner and the TUI.
  - Two stores of one command that map to the same variable (`my-app` and `my_app`) are an error (exit `1`),
    unless a higher-precedence source gives the key for both.
  - A variable that is set but empty or not a valid key is a key error (exit `4`); the message names the
    variable, never its value. A key that does not decrypt the store is the usual decryption error (exit `4`).
  - Variables of stores that are not used are ignored. A variable for a used plaintext store is ignored too
    (environments are shared; unlike `-k`, it was not given for this command).
  - New keys never come from the environment: `create-store -e`, `encrypt`, `rekey --new-key` and the
    `cp-store` / `mv-store` new-key options keep their explicit options. `rekey`'s *old* key may come from it.
  - `run` removes every `ENV_STORE_KEY_*` variable from the child's environment, so the program never inherits
    keys. The library does not change `os.environ` apart from what `apply` writes.
  - The docs include a deployment guide (Heroku, Kubernetes) that also shows mounting a Secret as a file with
    `-k` / `[keys]`, which keeps the key out of the process environment, and states that encryption protects the
    backend and its backups, not against someone who can read the deployment's configuration.
- The tool never stores, caches or remembers keys.

### 4.4 Which operations need the key

| Operation | Key needed |
|---|---|
| `ls-store` | no |
| `create-store --encrypt` | a new key (generated, existing file, or passphrase) |
| `rm-store` | no (D21) |
| `ls`, `get`, `set`, `rm`, `import` | yes |
| `export`, `export-shell`, `run` | yes, for every encrypted store in the list |
| `rekey` | old and new key |
| `encrypt` | new key |
| `keygen` | no |
| `cp-store`, `mv-store` *(if included, Q15)* | yes |

**CRUD on encrypted stores** happens entirely in the core: `read_store` → decrypt → change the variables in memory →
encrypt with a fresh nonce → `write_store`. Adapters never see plaintext of an encrypted store.

### 4.6 Concurrent writes *(decided, D7)*

Applies to **all** stores, encrypted or not.

- Every store record has an integer `revision`, starting at `1` and incremented by every successful write.
- A write only succeeds if the stored revision still equals the revision that was read. Otherwise the adapter raises
  `ConcurrentModificationError` and nothing is written.
- No automatic retry. The CLI reports the conflict (exit code `5`) and the user runs the command again.
- Nothing is ever overwritten silently.
- Each adapter implements the check atomically:
  - SQL: `UPDATE … SET …, revision = revision + 1 WHERE name = ? AND revision = ?`, conflict if 0 rows changed.
  - Local files: exclusive lock file per store while checking the revision and replacing the file (atomic
    `os.replace`).

### 4.5 Key lifecycle commands *(decided, D4)*

| Command | Purpose |
|---|---|
| `keygen <path>` | Write a new random key file (mode `0600`). Refuses to overwrite an existing file. `keygen -` prints the key to stdout, e.g. to put it straight into a password manager. |
| `rekey -s <store>` | Re-encrypt a store with a new secret. Needs the old key (`-k`) and a new one: `--new-key <path>`, `--generate-key <path>` or `--passphrase`. Can switch between `keyfile` and `passphrase` mode. Generates a new salt. |
| `encrypt -s <store>` | Turn a plaintext store into an encrypted one. Takes the same new-key options as `rekey`. |

- **No `decrypt` command.** An encrypted store never turns back into a plaintext store in place. To get a plaintext
  copy, the user creates a new, unencrypted store and copies the contents into it (via `import` or `cp-store`,
  depending on Q15). This makes removing encryption a deliberate act.

---

## 5. Configuration

Configuration is done via environment variables. Each environment variable has a CLI option that takes
precedence: `-c/--connection` for `ENV_STORE_CONNECTION`, and the per-command `--first-wins` for
`ENV_STORE_ORDERED_OVERWRITE` (D39).

### 5.1 `ENV_STORE_CONNECTION`

Defines the connection string and therefore the adapter. Standard PostgreSQL and SQLite connection strings are
supported. Local files use `json://path/to/directory` or `toml://path/to/directory` (D9). This makes connecting to
any storage provider a one-liner; the adapters implement the actual connection.

**No default** *(decided, D29)*: if no connection is configured (no `-c`, no `ENV_STORE_CONNECTION`, no
`connection` in the project file), every command that opens a store fails with a message that explains these three ways to set it. No
data is ever written to a location the user didn't choose. *(Amended in phase 3:)* `keygen`, `--help` and
`--version` open no store and work without a connection; they do not read the project file either (D44).

### 5.2 `ENV_STORE_ORDERED_OVERWRITE`

Default: `true`.

If `true`, variables present in several stores are applied in load order when exporting a dotenv file or loading
into an environment (`export`, `os.environ`, …). The variable from the store loaded last wins. If `false`, variables
are not overwritten (first wins).

**CLI override** *(decided, D14)*: `--first-wins` on every command that merges stores (`ls`, `get`, `export`,
`export-shell`, `run`). It takes precedence over the environment variable.

*(decided, D39)* Last wins is the default and the intended behaviour, so `--first-wins` is the only CLI override.
There is no `--last-wins`: when `ENV_STORE_ORDERED_OVERWRITE=false` or `ordered_overwrite = false` in the project
file selects first wins, last wins is restored by unsetting or changing that setting, not by a flag.

> *(decided, D33)* accepted values `true/false/1/0/yes/no` (case-insensitive).

---

## 6. CLI

**Framework** *(decided, D19)*: the CLI is built with **typer** and ships in the `cli` extra (typer, and through it
click, rich and shellingham). The core has no CLI dependencies.

**Executable** *(decided, D20)*: `environment-store`, with the short alias `envs`. Both are installed as entry points.

**Exit codes** *(decided, D24)*

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Usage or validation error (including a refused schema setup, §3.3.2) |
| `2` | Not found (store or variable) |
| `3` | Already exists |
| `4` | Decryption or key error (wrong key, missing key in non-interactive use) |
| `5` | Concurrent modification (D7) |

`run` is the exception: it returns the exit code of the command it runs.

**Further conventions** *(decided, D33, D35)*
- Global options: `-c, --connection` (overrides `ENV_STORE_CONNECTION`), `--no-project` (ignore the project file,
  §6.0.3), `--noinput` (see below).
- `-h` is a shorthand for `--help` on `envs` and on every command *(D48)*.
- **Reference pages** *(D49)*: a man page `envs(1)` (also reachable as `environment-store(1)`) and a tldr page ship
  with the project. The wheel installs the man page under `share/man/man1`, so `man envs` works wherever the
  install prefix's man directory is on `MANPATH`. A test keeps both pages in step with the commands.
- Output goes to stdout, diagnostics to stderr.
- Destructive commands ask for confirmation on a TTY; `-y, --yes` skips it. Non-TTY without `--yes` fails.
- `--json` output for `ls-store`, `ls` and `get` for scripting.
- **`--noinput`** (D35), meant for CI: never prompt, even when attached to a terminal. Anything that would prompt
  fails instead: a missing key or passphrase with exit code `4`, a missing confirmation (no `-y`) with exit code `1`.
  `set` without `KEY=VALUE` then reads only from stdin.

**Overwrite flags** *(decided, D14)*

| Flag | Meaning | Used by |
|---|---|---|
| `-o, --overwrite` | Overwrite existing **variables** | `set`, `import`, `export-shell`, `run` |
| `--force` | Replace an existing **output file** | `export` |
| `--first-wins` | Merge order between **stores**: first store wins instead of last (overrides `ENV_STORE_ORDERED_OVERWRITE`) | `ls`, `get`, `export`, `export-shell`, `run` |

### 6.0 Selecting stores and keys *(decided, D16, D17)*

#### 6.0.1 Reading commands: positional store list

Every command that reads and merges stores (`ls`, `get`, `export`, `export-shell`, `run`) uses the **same** format:

- Stores are **positional arguments**. Left to right is the load order.
- Keys are bound **by store name**: `-k <store>=<path>`, repeatable. `-k <store>=-` reads that store's key from
  stdin.
- An encrypted store without `-k` is prompted for on a terminal (D3), once per store. Non-interactive: exit code `4`.
- With a single store, `get` and `ls` are simply the one-store case of the same syntax.

```bash
envs export -f .env base_conf db_certs customer_a staging_env \
  -k db_certs=./dbc.key -k customer_a=-

envs ls base_conf staging_env -v
envs get DB_HOST base_conf staging_env      # value that wins under the merge rules
envs run base_conf staging_env -- python app.py
```

- `-k` for a store that isn't in the list, or for an unencrypted store, is an error.
- Because keys are bound by name, the syntax works with any CLI framework and with Windows paths.

> *(decided, D33)* when exactly one store is given, `-k <path>` without `store=` is accepted as a shorthand.

#### 6.0.2 Writing commands: one store via `-s`

> *(decided, D33)* commands that change a store (`set`, `rm`, `import`, `rekey`, `encrypt`) always act on exactly one
> store, named explicitly with `-s, --store`. Their key is given as `-k <path>` (or `-k -`). They never take the
> store from the project file, so a write never lands in a store by accident. Commands that act on a whole store by
> name (`create-store`, `rm-store`, `cp-store`, `mv-store`) take it as a positional argument.

#### 6.0.3 Project file *(decided, D17, D25)*

An optional project file saves the store list and key paths, so they don't have to be retyped. It is configuration
for **users** of environment-store, in whatever project they work on (Python, Node, Go, CI pipelines …), so it is a
dedicated file and not part of `pyproject.toml`.

```toml
# .envstore.toml
stores = ["base_conf", "db_certs", "customer_a", "staging_env"]

[keys]
db_certs   = "~/.keys/dbc.key"
customer_a = "~/.keys/a.key"
```

```bash
envs export -f .env
envs run -- python app.py
```

- Searched in the current directory, then in its parents (like `.git`). The first one found is used.
- Stores given on the command line **replace** the file's list. `-k` on the command line overrides the file's key
  for that store.
- `--no-project` ignores the file.

| Key | Type | Description |
|---|---|---|
| `stores` | list of strings | Default store list for reading commands, in load order |
| `[keys]` | table store → path | Key file per encrypted store. Paths are relative to the file's directory; `~` is expanded. Paths only, never key material. |
| `ordered_overwrite` | bool | Default merge order. Precedence: `--first-wins` > `ENV_STORE_ORDERED_OVERWRITE` > project file > default (`true`) |
| `connection` | string | Connection string. Precedence: `-c` > `ENV_STORE_CONNECTION` > project file |

> *(decided, D33)* if the file's `connection` contains a password, every command prints a warning that credentials
> should not be stored in a file that may be committed, and recommends `ENV_STORE_CONNECTION` instead.

### 6.1 Command overview

| Command | Purpose |
|---|---|
| `ls-store` | List all stores and whether they are encrypted |
| `create-store <name>` | Create a store |
| `rm-store <name>` | Delete a store |
| `cp-store <src> <dst>` | Copy a store, optionally into another backend *(D15)* |
| `mv-store <src> <dst>` | Rename or move a store *(D15)* |
| `ls [stores…]` | List the variables of one or more stores (merged) |
| `get <key> [stores…]` | Print the value of a variable (merged) |
| `set -s <store> …` | Set one or more variables |
| `rm -s <store> <key>…` | Delete variables |
| `import -s <store>` | Fill a store from a dotenv / JSON / TOML file *(D15)* |
| `export [stores…]` | Export one or more stores to a file (dotenv, JSON, TOML) |
| `export-shell [stores…]` | Print shell statements that load one or more stores into the current shell |
| `run [stores…] -- <cmd>` | Run a command with the merged environment *(D15)* |
| `keygen <path>` | Generate a key file *(D4)* |
| `rekey -s <store>` | Re-encrypt a store with a new key or passphrase *(D4)* |
| `encrypt -s <store>` | Turn a plaintext store into an encrypted one *(D4)* |
| `migrate` | Create / upgrade the SQL schema *(D11)* |
| `tui` | Start the TUI (needs the `tui` extra) *(D15)* |

Dropped from V1: `children`, `levels`, `delete-level` (hierarchy concepts), `export-dotenv` (merged into `export`),
`transfer` (replaced by `cp-store` / `mv-store`). Rejected for V2: `decrypt` (D4).

### 6.2 `ls-store`

Lists all available stores with the information whether they are encrypted.

*(decided, D42)* When the backend holds no stores, stdout stays empty (`[]` with `--json`), exit `0`, and stderr says
`no stores in <location>` with the resolved location (absolute directory, database file, or PostgreSQL host,
database and schema without the password), so a mistyped connection is visible.

### 6.3 `create-store <store-name>`

Creates a new store.

| Option | Type | Description |
|---|---|---|
| `-e, --encrypt` | flag | Create an encrypted store. Requires exactly one of the three key options below. |
| `-k, --key <path>` | param | Use an existing key file (`keyfile` mode). `-k -` reads it from stdin. |
| `--generate-key <path>` | param | Generate a new key file at `<path>` (mode `0600`, refuses to overwrite) and use it (`keyfile` mode). |
| `--passphrase` | flag | `passphrase` mode. The passphrase is read from stdin if piped, otherwise prompted twice (hidden). |

- Fails if the store already exists.
- There is no `--cipher` option in V2.0 because there is only one cipher (D2). It will be added together with the
  second cipher.

### 6.4 `rm-store <store-name>`

Deletes a store.

*(decided, D21)*: no key is needed, also for encrypted stores. Deleting acts on the store, not its contents, and a
store whose key is lost must still be removable. A confirmation is required on a terminal; `-y, --yes` skips it
(and is required in non-interactive use).

### 6.5 `cp-store <src> <dst>` / `mv-store <src> <dst>` *(D15)*

Copy a store under a new name, or rename it. `--to <connection>` copies or moves it into another backend (then
`<dst>` may equal `<src>`). `mv-store` is `cp-store` followed by `rm-store <src>`, done so that a failure never
leaves zero copies.

> **encryption of the target** *(decided, D33)*
> - Default: the target has the same encryption as the source, with the same key. It is re-encrypted, because the
>   ciphertext is bound to the store name (D5). Needs the source key (`-k <path>`).
> - `--plain`: the target is an unencrypted copy. This is the documented way to get a plaintext version of an
>   encrypted store (D4).
> - `--new-key <path>`, `--generate-key <path>`, `--passphrase`: the target is encrypted with a different secret.
> - Fails if `<dst>` already exists.

### 6.6 `ls [stores…]`

Lists the variables of one or more stores. With several stores, it shows the merged result.

| Option | Type | Description |
|---|---|---|
| `[stores…]` | positional | Stores in load order (§6.0.1); default from the project file |
| `-v, --values` | flag | Also show the values |
| `--source` | flag | Show which store each variable's winning value comes from |
| `--first-wins` | flag | First store wins instead of last |
| `-k <store>=<path>` | param | Key for an encrypted store; repeatable |

### 6.7 `get <key> [stores…]` *(decided, D16)*

Prints the value of a variable. With several stores, it prints the value that wins under the merge rules.

| Option | Type | Description |
|---|---|---|
| `<key>` | positional | Variable name |
| `[stores…]` | positional | Stores in load order (§6.0.1); default from the project file |
| `--first-wins` | flag | First store wins instead of last |
| `-k <store>=<path>` | param | Key for an encrypted store; repeatable |

> *(decided, D33)* prints the raw value without a trailing newline when stdout is not a terminal, so
> `$(envs get DB_HOST base_conf)` works for multi-line values too. Exit code `2` if the variable is in none of the
> stores.

### 6.8 `set -s <store>` *(decided, D18)*

Sets one or more variables in one store, in a single write (one revision).

| Form | Example | Allowed for |
|---|---|---|
| `KEY=VALUE` pairs | `envs set -s base_conf DB_HOST=localhost DB_PORT=5432` | **Unencrypted stores only** (values on the command line end up in shell history) |
| Stdin | `envs set -s customer_a DB_PASSWORD < secret.txt` | All stores; also the way to set multi-line values. One trailing newline (LF or CRLF) is stripped, as for passphrase files (D3), so `echo secret \| envs set …` stores `secret`. *(D41)* Stdin with zero bytes (e.g. `< /dev/null`, or a forgotten pipe in CI) is an error (exit 1) so a variable is never blanked by accident; an empty value is set with `echo \| envs set …` (the newline is stripped) or `KEY=` |
| Hidden prompt | `envs set -s customer_a DB_PASSWORD` (on a terminal) | All stores; asks twice to confirm, and asks again (up to three attempts) when the two entries differ |

| Option | Type | Description |
|---|---|---|
| `-s, --store` | param | The store to write to |
| `-o, --overwrite` | flag | Overwrite variables that already exist (otherwise: error, nothing is written) |
| `-k, --key` | param | Key file (`-k -` for stdin) if the store is encrypted |

- There is no positional `set KEY VALUE` form.
- `KEY=VALUE` on an encrypted store is refused with a hint to use stdin or the prompt.
- Stdin and `-k -` can't be used together in one call.

### 6.9 `rm -s <store> <key>…`

Deletes one or more variables from one store, in a single write.

| Option | Type | Description |
|---|---|---|
| `-s, --store` | param | The store to change |
| `-k, --key` | param | Key file (`-k -` for stdin) if the store is encrypted |

### 6.10 `import -s <store>` *(D15)*

Fills an existing store from a file.

| Option | Type | Description |
|---|---|---|
| `-s, --store` | param | Target store (must exist; encryption is chosen with `create-store`) |
| `-f, --file` | param | Input file; omitted → stdin (D22) |
| `-t, --type` | param | `dotenv` \| `json` \| `toml`; omitted → inferred from the extension, dotenv for stdin (D22) |
| `-o, --overwrite` | flag | Overwrite existing variables (otherwise: error listing the conflicts, nothing is written) |
| `-k, --key` | param | Key file if the store is encrypted |

> *(decided, D33)* JSON and TOML input must be a flat object of string values. Nested input (e.g. a `--nested` export)
> is refused.

### 6.11 `export [stores…]`

Exports variables to the requested file format. Multiple stores are loaded in order (§6.0.1).

```bash
envs export -f .env -t dotenv base_conf db_certs customer_a staging_env \
  -k db_certs=./dbc.key -k customer_a=./key.enc
```

| Option | Type | Description |
|---|---|---|
| `[stores…]` | positional | Stores in load order; default from the project file |
| `-f, --file` | param | Output file |
| `-t, --type` | param | File type: `dotenv` \| `json` \| `toml` |
| `--force` | flag | Replace an existing output file |
| `--nested` | flag | Do not merge; put each store under its own key (see below) |
| `--first-wins` | flag | First store wins instead of last |
| `-k <store>=<path>` | param | Key for an encrypted store; repeatable |

**Defaults** *(decided, D22)*: `-f` omitted → write to stdout. `-t` omitted → inferred from the file extension
(`.env*` → dotenv, `.json`, `.toml`); dotenv when writing to stdout.

**Nested mode:** instead of overwriting variables, the stores are used as keys with their variables and values
below them. For dotenv files, each variable is prefixed with the store name in SCREAMING_SNAKE_CASE, joined by a
**double underscore** *(decided, D30)*. A remaining collision is reported as an error.

```jsonc
// --nested -t json
{ "base_conf": { "DB_HOST": "localhost" }, "customer_a": { "DB_HOST": "10.0.0.5" } }
```

```dotenv
# --nested -t dotenv
BASE_CONF__DB_HOST=localhost
CUSTOMER_A__DB_HOST=10.0.0.5
```

> *(decided, D37, replaces the D33 wording; amended after measuring python-dotenv 1.2)* dotenv quoting, compatible
> with python-dotenv and Docker Compose:
>
> 1. unquoted for non-empty values made only of `[A-Za-z0-9_./:@%+,-]`;
> 2. single quotes for single-line values without `'`, without `\\` and not ending in `\` (python-dotenv decodes
>    `\\` and `\'` inside single quotes; any other backslash stays literal);
> 3. double quotes with `\\`, `\"`, `\n`, `\r`, `\t` escapes for all other values, as long as they contain no `$`;
> 4. refused, with a hint to use `-t json`, `-t toml` or `run`: values that need double quotes **and** contain `$`
>    (Compose interpolates `$` in double quotes), and values containing `${` in any form (python-dotenv interpolates
>    `${…}` even inside single quotes).
>
> Importing dotenv never interpolates: `${X}` is stored as written.

### 6.12 `export-shell [stores…]`

Like `export` with type `dotenv`, but the output is shell statements that load the variables into the current
shell (Unix `export`).

| Option | Type | Description |
|---|---|---|
| `[stores…]` | positional | Stores in load order; default from the project file |
| `-o, --overwrite` | flag | Overwrite variables that are already set in the shell |
| `--nested` | flag | Instead of overwriting, prefix variables with the store name in SCREAMING_SNAKE_CASE |
| `--first-wins` | flag | First store wins instead of last |
| `-k <store>=<path>` | param | Key for an encrypted store; repeatable |

> **Technical constraint:** a child process cannot modify the environment of its parent shell. `export-shell`
> therefore **prints** shell statements that the user evaluates:
>
> ```bash
> eval "$(envs export-shell base_conf staging_env)"
> ```
>
> Without `--overwrite`, the generated statements skip variables already set in the shell, e.g.
> `[ -n "${DB_HOST+x}" ] || export DB_HOST='…'` (this form keeps the exit status 0 when
> the last variable is already set, so `eval` does not fail). Values are quoted with `shlex.quote`.

**Shells** *(decided, D23)*: POSIX shells only (bash, zsh, dash, …). fish and PowerShell users use `run`, which works
independently of the shell.

### 6.13 `run [stores…] -- <cmd>` *(D15)*

Runs a command with the merged environment added to the current one. The shell and the file system are not
touched.

| Option | Type | Description |
|---|---|---|
| `[stores…]` | positional | Stores in load order; default from the project file |
| `-o, --overwrite` | flag | Store values overwrite variables already set in the current environment |
| `--nested` | flag | Prefix variables with the store name instead of merging |
| `--first-wins` | flag | First store wins instead of last |
| `-k <store>=<path>` | param | Key for an encrypted store; repeatable |

> *(decided, D33)* the exit code of `run` is the exit code of `<cmd>`. On POSIX the process is replaced (`execvpe`), so
> signals reach the command directly.

### 6.14 `tui` *(D15)*

Starts the TUI. Needs `environment-store[tui]`; without it, the command fails with a hint to install the extra.

*(decided, D46)* The Textual command palette is disabled, because its Screenshot action could save revealed values
to disk. Every screen's footer lists the keys that work there (including Enter to open or edit), and dialogs show
their own keys.

---

## 7. Extras and architecture

### 7.1 Layering *(decided, D31)*

```
 core package (environment-store)
 ┌───────────────────────────────────────────────────────────────┐
 │ models · merge · crypto · adapter contract · json/toml/sqlite │
 │ Python library = public facade (EnvironmentStore, load, …)    │
 └──────┬───────────────┬───────────────┬────────────────────────┘
        │               │               │
   ┌────▼────┐     ┌────▼────┐     ┌────▼────┐
   │   cli   │     │   tui   │     │   api   │
   └─────────┘     └─────────┘     └────┬────┘
                                        │ HTTP only
                                   ┌────▼────┐
                                   │   web   │
                                   └─────────┘
```

- The Python library is the public facade of the core and ships in the core package. It is not a separate extra.
- CLI, TUI and API each use the library directly. None of them depends on another one.
- The web interface is a frontend that only talks to the API.

### 7.2 API and web interface *(decided, D32)*

- **Client-side decryption only.** The API never receives keys and never sees the plaintext of encrypted stores. It
  stores and serves ciphertext; the client (library, CLI, TUI, browser) decrypts.
- This makes the API just another backend from the client's point of view: an `https://` connection string handled by
  an API adapter.
- The web interface therefore decrypts in the browser (WebCrypto AES-GCM plus an Argon2id WASM library, D34).
- Only these principles are decided now. Framework, endpoints and authentication get their own spec once core, CLI
  and TUI are done. API and web interface are not part of V2.0.

### 7.3 Python library and packaging

> **Python library API** *(decided as direction, D33, D36; exact names are settled test-first)*
>
> ```python
> import environment_store
>
> # One-liner (D36), like python-dotenv's load_dotenv(): resolves connection, project file and keys exactly
> # like the CLI (incl. prompts on a terminal) and applies the merged result to os.environ.
> environment_store.load("base_conf", "staging_env")
> environment_store.load()                     # stores from the project file
>
> from environment_store import EnvironmentStore, Source
>
> es = EnvironmentStore.from_env()            # reads ENV_STORE_CONNECTION
> es = EnvironmentStore("sqlite:///envs.db")  # explicit
>
> es.create_store("customer_a", encrypt=True, key=Path("./key.enc"))
> es.set("base_conf", "DB_HOST", "localhost", overwrite=True)
>
> env = es.load([Source("base_conf"), Source("customer_a", key=Path("./key.enc"))])
> env.apply()                                  # writes into os.environ
> env.to_file(".env", fmt="dotenv")
> ```

> **packaging (pip extras)** *(decided, D33)*
>
> | Extra | Adds | Dependencies |
> |---|---|---|
> | *(core)* | file + SQLite adapters, library, encryption | `cryptography` only (D6) |
> | `postgres` | PostgreSQL adapter | `psycopg` |
> | `cli` | CLI | `typer` (D19) |
> | `tui` | TUI | `textual` |
> | `api` | HTTP API (after V2.0, D32) | framework not chosen yet |
> | `web` | Web interface (after V2.0, D32) | talks to `api` over HTTP |
> | `aws` | AWS adapters (later) | `boto3` |
> | `all` | everything | |
>
> **Documentation of installs** *(D50, D51)*: the docs lead with uv: `uvx` for one-off runs, `uv tool install` for the
> CLI, `uv add` for the library; pip is shown as the alternative. Installation docs explain every extra in a table:
> what it adds, its dependencies, which commands or features need it, and the uv and pip commands to install it.

---

## 8. Tooling and quality

- Python **3.13+**
- **ruff** for formatting and linting
- **ty** type checking, enforced everywhere (no untyped code, CI-blocking)
- **Test-driven development**
- **100 % code coverage** (line and branch), enforced in CI
- An adapter system and modularisation similar to V1, but cleaner

> *(decided, D33)* `uv` for environment and builds (as today); PostgreSQL tests run against a real database in CI
> (service container), SQLite and file adapters run everywhere; shared adapter contract tests; `pytest` +
> `coverage --fail-under=100 --branch`.

---

## 9. Non-goals for V2.0

> *(decided, D33)*
> - No hierarchy, inheritance or references between stores.
> - No access control / users / permissions in the core (only possible later via API).
> - No versioning or history of variable values.
> - No backward compatibility or migration path from V1.
> - No AWS adapters in the first release.
> - No HTTP API and no web interface in the first release (decided, D32).
> - No `decrypt` command (decided, D4).

---

## 10. Original TODOs

- [x] Select encryption methods → [§4.2](#42-cipher-decided-d2) (D2)
- [x] Evaluate how to handle encrypted stores (CRUD) → [§4](#4-encryption) (D1, D3, D4); D5–D7
- [x] Evaluate current CLI commands, extend or slim down where needed → [§6.1](#61-command-overview) (D14–D24)

---

## 11. Open questions

None. All questions from the refinement round and all drafting proposals are decided; see the
[Decision log](#12-decision-log).

---

## 12. Decision log

| # | Date | Topic | Decision | Was |
|---|---|---|---|---|
| D1 | 2026-11-06 | Encryption scope | Whole store is encrypted as one blob; only name and metadata stay visible. `ls` needs the key. | Q7 |
| D2 | 2026-11-06 | Cipher | AES-256-GCM only, in two modes: random key file and passphrase (KDF changed from scrypt to Argon2id by D34). Cipher ID stored per store for later additions (e.g. age). | Q8 |
| D3 | 2026-11-06 | Key input | Key file path (`-k path`), stdin (`-k -`), hidden prompt on a TTY. No literal keys on the CLI, no env vars for keys. | Q9 |
| D4 | 2026-11-06 | Key lifecycle | `keygen`, `rekey`, `encrypt` are in V2.0. No `decrypt`: plaintext copies are made by creating a new store and copying the contents into it. | Q10 |
| D5 | 2026-11-06 | Encryption AAD | Ciphertext is bound to store name + format version + cipher metadata. Renaming an encrypted store needs its key. | Q24 |
| D6 | 2026-11-06 | Dependencies | `cryptography` is a required core dependency (the only one). | Q25 |
| D7 | 2026-11-06 | Concurrency | Optimistic locking with a `revision` counter on every store; conflicting writes fail with `ConcurrentModificationError` (exit code 5), no automatic retry. | Q26 |
| D8 | 2026-11-06 | SQL data model | One row per store with one payload (JSON for plaintext, ciphertext for encrypted). No per-variable table. | Q4 |
| D9 | 2026-11-06 | File adapters | Separate schemes `json://dir` and `toml://dir`, one file per store; replaces `local://`. | Q5 |
| D10 | 2026-11-06 | SQL libraries | Stdlib `sqlite3`, `psycopg` 3 for PostgreSQL, built-in migration runner. No ORM. | Q6 |
| D11 | 2026-11-06 | Schema migrations | SQLite: create and upgrade automatically. PostgreSQL: create automatically, upgrade only via `migrate`. First setup needs a clean database; otherwise warn and do nothing. Details in D13. | — |
| D12 | 2026-11-06 | Initial SQL schema | Schema v1: key-value `meta` table (app marker + schema version) and `stores` table per D8 with plaintext/encrypted check constraint. | Q27 |
| D13 | 2026-11-06 | First setup / isolation | PostgreSQL: dedicated schema, default `environment_store`, configurable via `?schema=`; clean = schema missing or empty. SQLite: clean = new file or no tables. Foreign content → warn and refuse. Newer schema than client → refuse. | Q27 |
| D14 | 2026-11-06 | Overwrite flags | `-o, --overwrite` always means overwrite existing variables; `--force` replaces an output file; `--first-wins` overrides `ENV_STORE_ORDERED_OVERWRITE`. | Q12 |
| D15 | 2026-11-06 | Additional commands | `import`, `cp-store`, `mv-store`, `run` and `tui` are in V2.0. | Q15 |
| D16 | 2026-11-06 | Selecting stores | Reading commands (`ls`, `get`, `export`, `export-shell`, `run`) share one format: stores as positional list in load order, keys bound by name with `-k store=path`. `get` and `ls` merge across stores. | Q17, Q20 (partly) |
| D17 | 2026-11-06 | Project file | Optional `.envstore.toml` (searched upwards) with default store list and key paths; CLI stores replace it, `--no-project` ignores it. Details in Q28. | — |
| D18 | 2026-11-06 | `set` input | `KEY=VALUE` pairs (unencrypted stores only), stdin, hidden prompt. No positional `set KEY VALUE`. | Q18 |
| D19 | 2026-11-06 | CLI framework | typer, in the `cli` extra. | Q20 |
| D20 | 2026-11-06 | Executable | `environment-store` plus alias `envs`. | Q13 |
| D21 | 2026-11-06 | `rm-store` | No key needed, also for encrypted stores; confirmation on a terminal, `-y` otherwise. | Q16 |
| D22 | 2026-11-06 | `export` / `import` defaults | No `-f` → stdout / stdin. No `-t` → inferred from the extension, dotenv for stdout / stdin. | Q19 |
| D23 | 2026-11-06 | Shells | `export-shell` supports POSIX shells only; others use `run`. | Q21 |
| D24 | 2026-11-06 | Exit codes | 0 success, 1 usage/validation, 2 not found, 3 exists, 4 key error, 5 concurrent modification; `run` passes through. | Q14 |
| D25 | 2026-11-06 | Project file details | Dedicated `.envstore.toml` only (it is end-user config, so not in `pyproject.toml`); may set `stores`, `[keys]`, `ordered_overwrite` and `connection`. | Q28 |
| D26 | 2026-11-06 | Terminology | The collection is called **store** everywhere; the storage location is the **backend**. | Q1 |
| D27 | 2026-11-06 | Store names | `^[a-z][a-z0-9_-]{0,62}$`, lowercase only (first character amended by D40). | Q2 |
| D28 | 2026-11-06 | Values | Any UTF-8 string incl. empty and multi-line; NUL forbidden; strings only. | Q3 |
| D29 | 2026-11-06 | Default connection | None; a missing connection is an error explaining how to set one, for every command that opens a store (amended in phase 3: `keygen`, `--help`, `--version` need none). | Q11 |
| D30 | 2026-11-06 | Nested dotenv separator | Double underscore: `BASE_CONF__DB_HOST`; remaining collisions are errors. | Q2 |
| D31 | 2026-11-06 | Layering | Library is the core's facade; CLI, TUI and API each use it directly; web talks only to the API. | Q22 |
| D32 | 2026-11-06 | API principles | Client-side decryption only; the API is another backend (`https://` adapter). Framework, endpoints and auth specified after V2.0. | Q23 |
| D33 | 2026-11-06 | Proposal review | All drafting proposals are accepted as written, except the changes in D34–D36. | — |
| D34 | 2026-11-06 | Passphrase KDF | Argon2id instead of scrypt (`t=3, m=64 MiB, p=4`, RFC 9106); requires `cryptography` ≥ 44. | review |
| D35 | 2026-11-06 | `--noinput` | Global flag for CI: never prompt; missing key → exit 4, missing confirmation → exit 1. | review |
| D36 | 2026-11-06 | Library one-liner | `environment_store.load(*stores)` resolves config like the CLI and applies to `os.environ`. | review |
| D37 | 2026-11-06 | dotenv quoting | Unquoted / single quotes (no `'`, no `\\`, no trailing `\`) / double quotes without `$`; refused: values needing double quotes with `$`, and any value containing `${` (python-dotenv interpolates it even in single quotes). Import never interpolates. Amended after golden tests against python-dotenv 1.2. | plan review, A4 |
| D38 | 2026-11-06 | `set` from stdin | One trailing newline (LF or CRLF) is stripped from a value read from stdin, like D3 for passphrase files; values that must end in a newline are set with `import`. | phase 3 plan review |
| D39 | 2026-11-06 | Merge-order override | Last wins is the default; `--first-wins` is the only CLI override of `ordered_overwrite`; no `--last-wins` flag. §5 no longer promises a CLI option for every setting in both directions. | phase 3 audit |
| D40 | 2026-11-06 | Store names are shell compatible | Amends D27: a store name cast to SCREAMING_SNAKE_CASE must be a valid POSIX shell variable name, so the first character must be `a-z`, not a digit. Every nested key `STORE__VAR` is then a valid variable name, and `export-shell`, `run --nested` and import of nested dotenv never refuse a store name. The store name rule must keep this property. | phase 3 review |
| D41 | 2026-11-06 | Empty stdin for `set` | Zero bytes on stdin is an error (exit 1); an empty value needs `echo \| envs set …` or `KEY=`. Prevents a forgotten pipe from blanking a variable. | docs review |
| D42 | 2026-11-06 | Empty `ls-store` | stdout empty (`[]` with `--json`), exit 0, stderr `no stores in <location>` with the resolved location. | docs review |
| D43 | 2026-11-06 | File-based backend paths | `json://`, `toml://` and `sqlite:///` all expand `~` and create a missing directory (mode `0700`) on first write; files `0600`. | docs review |
| D44 | 2026-11-06 | Commands without a connection | `keygen`, `--help` and `--version` read neither the connection nor the project file, so a broken `.envstore.toml` cannot stop them. | docs review |
| D45 | 2026-11-06 | New key from stdin | When a new store key comes from stdin (`create-store -e -k -`, `encrypt -k -`, `rekey --new-key -`, `cp-store`/`mv-store --new-key -`), the CLI warns on stderr that envs does not save the key and the store is unreadable without it. | docs review |
| D46 | 2026-11-06 | TUI command palette | Disabled: its Screenshot action could write revealed values to disk. | docs review |
| D47 | 2026-11-06 | Library error wording | Library errors name library parameters (`overwrite=True`, `force=True`, `fmt=`, `keys=`); the CLI and TUI add their own hints (`-o`, `--force`, `-t`, `-k`). Key text (`envstore-key-v1:…`) can be passed to the library without a file. | docs review |
| D48 | 2026-11-07 | `-h` | `-h` is a shorthand for `--help` on `envs` and every command. | usability test |
| D49 | 2026-11-07 | Reference pages | A man page `envs(1)` / `environment-store(1)`, installed by the wheel under `share/man/man1`, and a tldr page in the tldr-pages format; a test keeps both in step with the commands. | usability test |
| D50 | 2026-11-07 | uv first in the docs | Install and run instructions lead with uv (`uvx`, `uv tool install`, `uv add`); pip is the alternative. | usability test |
| D51 | 2026-11-07 | Extras explained | The installation docs explain every extra in a table: what it adds, dependencies, which commands need it, uv and pip install commands. | usability test |
| D52 | 2026-11-07 | Merged output order | Variables are output in store load order; within a store sorted by name; a variable shared by several stores keeps its first position and takes the merge order's value. Applies to `ls`, `export`, `export-shell`, `run` and the library. Amends PD 13. | usability test |
| D53 | 2026-11-07 | Key from the environment | Amends D3: an existing store's key or passphrase may come from `ENV_STORE_KEY_<STORE>` (store name in SCREAMING_SNAKE_CASE). Precedence `-k`/`key=` > variable > `[keys]` > prompt; colliding names are an error; new keys never come from it; `run` strips `ENV_STORE_KEY_*` from the child. For Heroku/Kubernetes deployments. | deployment question |
