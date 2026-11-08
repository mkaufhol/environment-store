# Architecture

Environment Store is one Python package, `environment_store`, in a `src/` layout. It is split into
layers with a strict import direction. The import direction is tested, so you can't break it by
accident.

## Repository layout

```text
src/environment_store/
├── __init__.py      public API, resolved lazily (import environment_store stays cheap)
├── _toml.py         minimal TOML writer (the standard library only reads TOML)
├── core/            domain model, validation, merge, errors, adapter contract, scheme registry
├── crypto/          key files, Argon2id, AES-256-GCM sealing
├── service.py       every store and variable operation, implemented once
├── adapters/
│   ├── files/       json:// and toml:// (one file per store)
│   ├── sql/         shared SQL schema, migrations, setup decisions, row codec
│   ├── sqlite/      sqlite:///
│   └── postgres/    postgresql:// and postgres:// (needs the postgres extra)
├── formats/         dotenv, JSON, TOML and POSIX shell import and export (pure)
├── config/          settings precedence, .envstore.toml, key sources, prompts
├── library/         the public Python facade the CLI and the TUI are built on
├── cli/             the envs command (typer, cli extra)
└── tui/             the terminal UI (textual, tui extra)
tests/               mirrors the layers, see testing.md
docs/                user documentation, man page, tldr page, this guide
.claude/skills/      the agent skill for using the envs CLI
```

## Layers and import rules

Each layer may import only from the layers in its row. `tests/unit/test_import_direction.py` holds
the same table as `ALLOWED_IMPORTS` and fails on any import outside it.

| Layer | May import from | Responsibility |
|---|---|---|
| `core` | `core` | Value objects, validation, merge, errors, the adapter protocol, the scheme registry. Standard library only. |
| `crypto` | `core`, `crypto` | Key files, key derivation and authenticated encryption. The only layer that uses `cryptography`. |
| `service` | `core`, `crypto`, `service` | `StoreService`: the only place where adapters and encryption meet. |
| `adapters` | `core` | The package root of the backends. It contains nothing but a docstring. |
| `adapters.sql` | `core`, `adapters.sql` | SQL shared by SQLite and PostgreSQL: DDL, migrations, setup decisions, record-to-row codec. |
| `adapters.files` | `core`, `adapters.files`, `_toml` | The JSON and TOML file backends. |
| `adapters.sqlite` | `core`, `adapters.sql`, `adapters.sqlite` | The SQLite backend. |
| `adapters.postgres` | `core`, `adapters.sql`, `adapters.postgres` | The PostgreSQL backend. |
| `formats` | `core`, `formats`, `_toml` | Pure readers and writers for dotenv, JSON, TOML and shell exports. |
| `config` | `core`, `crypto`, `config` | Settings precedence, the project file, `ENV_STORE_KEY_<STORE>`, key sources, prompts. |
| `library` | `core`, `crypto`, `service`, `formats`, `config`, `library` | The public API: `EnvironmentStore`, `Environment`, `load()`. |
| `cli` | `core`, `config`, `library`, `formats`, `cli` | The `envs` command: options, prompts, output, exit codes. |
| `tui` | `core`, `config`, `library`, `formats`, `tui` | The terminal UI. |

What the table means in practice:

- **The frontends never touch storage or crypto directly.** `cli` and `tui` go through `library`.
  When the TUI needs to tell a key from a path, it calls `library.keys.parse_key_text`. It never
  imports `crypto`.
- **Adapters store opaque records.** They never import `crypto` or `service`, so a backend can't
  see plaintext of an encrypted store, and adapters never import each other.
- **`config` knows nothing about formats or the library.**
- **One exception:** `environment_store.cli.tui_command` may import `tui`, and only inside the
  command function, so the `tui` extra loads only when `envs tui` runs. The TUI never imports the
  CLI.

How the checks work, and what trips people up:

- **Every import counts.** The static check walks every `import` statement, including the ones
  inside functions and inside `if TYPE_CHECKING:`. Making an import lazy or type-only does not get
  around the rule.
- **A second check imports each layer in a fresh interpreter** and fails if a higher layer ends up
  in `sys.modules`.
- **Restricted layers may not import the root package.** Write
  `from environment_store.core.errors import ValidationError`, never `import environment_store`.
- **Every package needs a row.** `_toml` and the root `__init__.py` are unrestricted. A new package
  or adapter subpackage must get its own row, which
  `test_every_package_and_adapter_subpackage_has_import_rules` enforces.
- **No import cycles.** `tests/unit/test_package.py` imports every module alone in a fresh
  interpreter, which catches cycles.

## What each layer does

### `core`: the domain

- **`core/models.py`:** the frozen value objects.
  - `StoreInfo`: name, encrypted, key mode, revision and timestamps.
  - `StoreRecord`: what an adapter stores. It holds either validated `variables` or a `ciphertext`
    with `cipher_meta`, never both. Build it with `StoreRecord.plain(...)` or
    `StoreRecord.sealed(...)`.
  - `Source`: a store name plus an optional secret, as the service takes it.
  - Revisions run from 1 to `MAX_REVISION`. Timestamps are timezone-aware and normalised to UTC.
- **`core/validation.py` and `core/names.py`:** the naming rules.
  - Store names are 1 to 63 lowercase letters, digits, `_` and `-`, starting with a letter.
    Lowercase only, because store names become file names on case-insensitive file systems.
  - Variable names are POSIX names. Values are any text without NUL or lone surrogates.
  - `key_variable("customer-a")` returns `ENV_STORE_KEY_CUSTOMER_A`.
  - Validation messages never echo a value.
- **`core/merge.py`:** how several stores combine.
  - `MergeOrder.LAST_WINS` is the default; `FIRST_WINS` is the alternative.
  - Variables keep the position where they first appeared and take the winning value.
  - The `nested` and `nested_flat` views (`STORE__VAR`) are here too.
- **`core/secrets.py`:** `KeyMaterial` (32 bytes) and `Passphrase`, together `Secret`. Their
  `repr` and `str` are redacted.
- **`core/errors.py`:** the error hierarchy, described in [Errors and exit codes](#errors-and-exit-codes).
- **`core/adapter.py`:** the `Adapter` and `MigratableAdapter` protocols, `SetupMode` and the
  `check_*` helpers. See [Adding a storage adapter](adapters.md).
- **`core/connection.py`:** the scheme registry `ADAPTER_FACTORIES` and `open_adapter()`.
- **`core/clock.py`:** `Clock` is a callable returning an aware `datetime`. It is passed in
  everywhere a timestamp is made, so tests control time.

### `crypto`: keys and sealing

- **Cipher:** AES-256-GCM with a fresh random 12-byte nonce for every write.
- **Key derivation:** Argon2id for passphrases, with RFC 9106 parameters and a random salt.
  `KdfParams` has upper bounds, so a tampered store can't force a huge key derivation.
- **The whole store is one sealed blob.** The plaintext is canonical JSON of all variables, so
  neither names nor values are visible in the backend.
- **The associated data binds the store name**, the payload format version and the cipher
  metadata. A ciphertext copied to another store name or with changed metadata fails to decrypt.
  That is why copying a store always re-seals it.
- **Every decryption failure is the same `DecryptionError`,** with one fixed message and no chained
  exception, so nothing about the content leaks.
- **Key files** are one line, `envstore-key-v1:` followed by unpadded URL-safe base64. They are
  created with mode `0600` and `O_EXCL`, and never overwritten.

`crypto/_sealing.py` is private: only `service.py` uses it.

### `service.py`: one implementation of every operation

`StoreService` wraps one adapter and does every store and variable operation:

- **Validation first.** It validates every name before the adapter is touched.
- **Read, modify, write.** Every write reads the record, changes it, re-seals it and writes it back
  with `write_store(..., expected_revision=...)`. A concurrent change raises
  `ConcurrentModificationError` instead of being overwritten silently.
- **Copy and move.** `copy_store` re-seals for the new name. `move_store` deletes the copy again if
  the source changed in the meantime.
- **Delete needs no key,** so a store whose key is lost can still be removed.
- **Only `Secret`s.** The service takes and returns `Secret` values and knows nothing about paths,
  environment variables, prompts or the project file. Turning those into a `Secret` is the job of
  `config` and `library`.

### `adapters`: storage

Adapters persist `StoreRecord`s and enforce the revision check atomically. They know nothing about
encryption. [Adding a storage adapter](adapters.md) describes the contract and the existing
backends.

### `formats`: import and export

The formats are pure functions over `str`, with no I/O:

- **`formats.dotenv`:** reads the python-dotenv grammar without interpolation. When writing, it
  refuses values that Docker Compose or python-dotenv would change on reading (`DotenvValueError`).
- **`formats.json_format` and `formats.toml_format`:** write flat or nested documents (`dumps`,
  `dumps_nested`), but read only flat documents of string values. Nested input is refused.
- **`formats.shell`:** writes POSIX `export` lines.

### `config`: where the settings come from

- **`config/settings.py`:** settings follow the precedence **option > environment variable >
  project file > default**.
  - The connection comes from `-c`, then `ENV_STORE_CONNECTION`, then `connection` in
    `.envstore.toml`. There is no default connection.
  - An empty environment variable counts as unset.
- **`config/project.py`:** finds and parses `.envstore.toml`.
  - It walks up from the working directory. The first project file it finds ends the search.
  - A file owned by another user, or a world-writable one, is ignored with a warning.
  - Unknown keys are errors.
- **`config/secrets.py`:** `SecretResolver` decides the key of an existing store, in this order:
  explicit key > `ENV_STORE_KEY_<STORE>` > project `[keys]` > prompt (interactive only) >
  `KeyRequiredError`.
- **`config/key_variables.py`:** reads `ENV_STORE_KEY_<STORE>`. A key variable for a plaintext store
  is ignored, because environments are shared.

### `library`: the public facade

- **`EnvironmentStore` (`library/store.py`):** owns one adapter and one `StoreService`.
  - Its methods mirror the CLI commands.
  - It turns a `Path`, `KeyMaterial` or `Passphrase` into a `Secret`. A plain `str` is refused,
    because it could be either a path or a passphrase.
  - It reads `ENV_STORE_KEY_<STORE>` for existing stores, but never the project file's `[keys]`, and
    it never prompts.
  - Its `repr` shows only the scheme, because the connection string may hold a password.
- **`environment_store.load()` (`library/oneliner.py`):** reproduces the CLI's configuration
  resolution for apps: settings, the project file, key precedence and prompts, but never stdin.
  Then it writes the merged variables into `os.environ`.
- **`Environment` (`library/environment.py`):** the merged result. It offers variables, sources,
  nested views, `apply()` and file output.

The library never prints, never exits and never reads stdin. Its error hints name library
parameters, such as `pass overwrite=True`.

### `cli` and `tui`: the frontends

The frontends own the terminal: prompts, output, exit codes and keyboard handling. They contain no
business rules: every rule they apply comes from `library`, `config` or `core`.

- **`cli/_typer.py`:** the group and command classes that override typer internals (`EnvsGroup`,
  `EnvsCommand`, `OfflineCommand`, `PassthroughCommand`). Apart from it, only the shell completion
  modules in `cli/completion/` touch typer internals.
- **`cli/runtime.py`:** the `Runtime` value collects every OS boundary (environment, working
  directory, TTY flags, prompter, `exec`, clock, adapter opener), so tests inject one instead of
  patching.
- **`tui/session.py`:** `StoreSession` does every store operation of the TUI through the library,
  so the screens stay thin. Other TUI modules use only small library helpers and types, such as
  `library.keys.parse_key_text` in the unlock dialog.

[Extending](extending.md) has the details and checklists for both.

## Two flows, end to end

### `envs -c json://stores get DB_HOST base dev`

1. **Entry.** The `envs` script calls `environment_store.cli:main`, which imports the typer app
   lazily, so a missing `cli` extra becomes a clean `MissingExtraError`.
2. **Settings.** The root callback in `cli/app.py` builds a `CliState`. Before the command's callback runs,
   `EnvsCommand.invoke` resolves the settings (`config/settings.py`), so a broken project file
   fails every command the same way. Only `keygen` and `completion`, which are `OfflineCommand`s,
   resolve no settings.
3. **Loading.** `cli/variables/reading.py` validates the variable name, then calls
   `cli/loading.py:load_for_reading`. In this order, it:
   - validates the store names and the `-k` options;
   - checks that every store exists, reporting all missing stores in one error;
   - checks for stores that share a key variable;
   - resolves the keys;
   - loads the stores.
4. **Opening the backend.** `CliState.open_store` creates an `EnvironmentStore`.
   `open_adapter` looks up the `json` scheme in `ADAPTER_FACTORIES`, imports
   `environment_store.adapters.files:open_json` and calls it with the URL. The store is closed
   automatically when the command ends.
5. **Decryption and merge.** `StoreService.load` reads each record and opens it with its secret.
   `Environment` merges the stores in load order.
6. **Output and errors.** `cli/output.py` writes the value. Any `EnvironmentStoreError` is caught in
   `EnvsGroup.invoke`, printed as `Error: ...` on stderr, and mapped to an exit code by
   `cli/errors.py`.

### `environment_store.load("base", "prod", keys={...})` in an app

1. `environment_store.load` resolves lazily to `library/oneliner.py:load`, which calls `load_with`
   with the real boundaries: `os.environ`, the working directory, the TTY state and a getpass
   prompter.
2. The settings are resolved exactly as in the CLI. A connection string with credentials in the
   project file becomes a `CredentialsInProjectFileWarning`.
3. Every store must exist before any key is read or prompted for. Then each key comes from
   `keys=`, `ENV_STORE_KEY_<STORE>`, the project's `[keys]`, or an interactive prompt, in that
   order.
4. `EnvironmentStore.load` decrypts and merges. `Environment.apply` writes into `os.environ` and
   keeps existing variables unless `overwrite=True`.
5. Errors reach the caller unchanged. There are no exit codes in the library.

## Errors and exit codes

Every library error derives from `EnvironmentStoreError` in `core/errors.py`. It carries a
`detail` and an optional `hint`. The CLI maps each error to an exit code by its category class
(`cli/errors.py`):

| Exit code | Category | Examples |
|---|---|---|
| 0 | success | |
| 1 | everything else | `ValidationError`, `ConfigurationError`, `MissingExtraError`, `BackendError` and their subclasses |
| 2 | `NotFoundError` | `StoreNotFoundError`, `VariableNotFoundError` |
| 3 | `AlreadyExistsError` | `StoreExistsError`, `VariableExistsError` |
| 4 | `CryptoError` | `KeyRequiredError`, `DecryptionError`, `InvalidKeyFileError`, `KeyModeMismatchError`, `KeySourceError` |
| 5 | `ConcurrentModificationError` | a store changed between read and write |

`envs run` is the exception: it passes its command's exit code through. Typer usage errors also exit
with 1, not click's 2.

The CLI replaces a library hint with a CLI remedy where one exists: `cli/errors.py` keeps the table
`_CLI_HINTS`, and the TUI keeps `_TUI_HINTS` in `tui/messages.py`. A new error class must derive
from the right category, or it silently exits with 1. [Extending](extending.md#add-an-error-class)
lists what else it needs.

## Optional extras and lazy imports

| Extra | Dependency | Imported by |
|---|---|---|
| `postgres` | psycopg | `adapters/postgres/`, which `open_adapter` imports only for a `postgresql://` or `postgres://` URL |
| `cli` | typer | `cli/app.py`, which `cli/__init__.py:main` imports inside the function |
| `tui` | textual | `tui/__init__.py`, which only `envs tui` imports, inside its command function |

A missing extra raises `MissingExtraError(extra)`. Its message gives the `uv add` and `pip install`
commands. `open_adapter` raises it only when the missing module is one the registry entry lists in
`requires`. Any other missing module is a bug and is re-raised unchanged.

`import environment_store` loads none of `library`, `config` or `service`. The public names in
`src/environment_store/__init__.py` resolve on first use through a module `__getattr__`.

## Design decisions worth knowing

- **No plugin system.** Backends are registered in the static `ADAPTER_FACTORIES` mapping and
  commands in explicit `register(app)` functions. Adding either means editing the code and its
  tests, which keeps every supported feature tested and documented.
- **Two `Source` classes.** `core.models.Source` (keyword-only, takes a `Secret`) is what the
  service uses. `library.sources.Source` (name positional, `key=` takes a `Path`, `KeyMaterial` or
  `Passphrase`) is the public `environment_store.Source`.
- **Dependencies are passed in.** The clock, the KDF parameter factory, the adapter opener, the
  prompter and the environment are parameters, never globals. Tests replace them with fakes
  instead of patching.
- **Untrusted input everywhere.** Store files, database rows, project files and key files are
  parsed as untrusted. A corrupt entry raises `BackendError` naming the location, never a value.
