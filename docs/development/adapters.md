# Adding a storage adapter

An adapter persists store records in one kind of backend. Encryption, validation of the variables,
merging and key handling all happen above it, in `service.py`, so an adapter is small: it stores
opaque `StoreRecord`s and enforces the revision check atomically.

## The existing adapters

| Scheme | Package | Storage | Schema | Extra |
|---|---|---|---|---|
| `json://dir` | `adapters/files` | one `<store>.json` file per store, with a lock file per store | none | — |
| `toml://dir` | `adapters/files` | one `<store>.toml` file per store, with a lock file per store | none | — |
| `sqlite:///file.db` | `adapters/sqlite` | standard library `sqlite3`, WAL mode | versioned, auto-upgraded | — |
| `postgresql://…` and `postgres://…` | `adapters/postgres` | psycopg, in a dedicated schema (default `environment_store`) | versioned, upgraded by `envs migrate` | `postgres` |

The JSON and TOML backends are one `FileAdapter` with two `FileSerializer`s. SQLite and PostgreSQL
share their schema, migrations, setup decisions and row codec in `adapters/sql`.

## The contract

`src/environment_store/core/adapter.py` defines the `Adapter` protocol. Implementations satisfy it
structurally; they don't inherit from it.

| Method | Must |
|---|---|
| `list_stores()` | return every store's `StoreInfo` without decrypting, sorted by name in code point order. Sort in Python if the backend collates differently. |
| `create_store(record)` | create atomically: of two racing creates, exactly one wins and the other raises `StoreExistsError`. The revision must be 1. |
| `read_store(name)` | return the record exactly as written, or raise `StoreNotFoundError` |
| `write_store(record, *, expected_revision)` | write only if the stored revision is still `expected_revision`, else raise `ConcurrentModificationError` and change nothing. `record.revision` must be `expected_revision + 1`. |
| `delete_store(name)` | delete, or raise `StoreNotFoundError` |
| `close()`, `__enter__`, `__exit__` | close idempotently. After `close()` every data method raises `BackendError`. `__exit__` never suppresses an exception. |

Rules for every method:

- **Check arguments before any I/O.** Validate store names and call the shared helpers first:
  - `check_create(record)` in `create_store`;
  - `check_write(record, expected_revision=...)` in `write_store`;
  - `check_writable(setup, location=...)` before any write.
- **Wrap backend failures.** Every OS or driver failure becomes a chained `BackendError`. Its
  message names a location without credentials, never a value.
- **Treat stored data as untrusted.** A corrupt file or row raises `BackendError`, or
  `UnsupportedFormatError` for an unknown format version.

### Setup modes

Every factory takes `setup: SetupMode`:

| Mode | Meaning |
|---|---|
| `AUTO` | the normal mode: create the location or schema when needed. SQLite also upgrades an outdated schema; PostgreSQL leaves that to `migrate()`. Foreign content or a newer schema is refused. |
| `NONE` | inspect and create nothing on open. `migrate()` sets up explicitly; otherwise the first data operation runs the `AUTO` setup lazily, so the adapter still works (the contract checks it). `envs migrate` opens backends in this mode. |
| `READ_ONLY` | write nothing at all, not even a lock or journal file. A missing location lists no stores. Every write raises `BackendError` containing "read-only". |

Shell completion opens backends in `READ_ONLY` mode on every Tab press, so this mode must be fast.
A network backend must bound every wait in it, as `adapters/postgres/read_only.py` does.

### Schemas and migrations

- **When you need it.** A backend with a versioned schema implements `MigratableAdapter`, which adds
  `migrate() -> MigrationReport`. `envs migrate` and `EnvironmentStore.migrate()` call it.
- **How it is detected.** `EnvironmentStore.migrate()` decides with
  `isinstance(adapter, MigratableAdapter)`. A runtime-checkable protocol only checks that the
  attribute exists, so **a backend without a schema must not define `migrate` at all.** Then
  `envs migrate` reports that the backend has no schema.
- **SQL backends.** A new SQL dialect reuses `adapters/sql`: add its DDL in `schema.py`, its
  migrations in `migrations.py`, a `Dialect` member in `codec.py`, and let `setup.py` decide whether
  to create, use or upgrade the schema.

## How a scheme reaches an adapter

There is no plugin or entry-point registry. `src/environment_store/core/connection.py` maps each
scheme to an import path:

```python
ADAPTER_FACTORIES: Final[Mapping[str, AdapterEntry]] = MappingProxyType(
    {
        "json": AdapterEntry(target="environment_store.adapters.files:open_json"),
        ...
        "postgresql": AdapterEntry(
            target="environment_store.adapters.postgres:open_postgres",
            extra="postgres",
            requires=("psycopg",),
        ),
    }
)
```

- **Lookup.** `open_adapter(url, setup=...)` reads the scheme, imports the target on first use and
  calls it as `factory(url, setup=setup)`. The factory gets the **whole** URL and parses it itself.
- **Missing extras.** If the import fails because a package in `requires` is missing, the user gets
  `MissingExtraError(extra)` with the install command. Any other missing module is re-raised as the
  bug it is.
- **Where to import the driver.** Import it at the top of the adapter package, not lazily inside a
  method, so `open_adapter` sees the missing module.

## Choose the shape first

- **A new file format** (one file per store, in a directory) doesn't need a new package.
  - Add a `FileSerializer` beside `JSON_SERIALIZER` and `TOML_SERIALIZER` in
    `src/environment_store/adapters/files/serializers.py`, and a factory beside `open_json` in
    `src/environment_store/adapters/files/adapter.py`.
  - `FileAdapter` already provides locking, atomic writes, the revision check and read-only mode.
  - Then follow steps 3 and 7 of the checklist below. Register the scheme in `ADAPTER_FACTORIES`
    and add it to `_DIRECTORY_SCHEMES` in `src/environment_store/core/connection.py` and to
    `_RELATIVE_DIRECTORY` in `src/environment_store/config/project.py`. Re-export the factory from
    `src/environment_store/adapters/files/__init__.py` (checked by
    `tests/adapters/files/test_package.py`), add golden files in `tests/adapters/files/golden/`,
    and update the scheme tests and the docs.
  - A format the standard library can't read or write needs a new runtime dependency, and that
    needs a deliberate decision (see [Tools](tooling.md#dependencies)).
- **A new SQL database** gets its own package under `adapters/` and reuses `adapters/sql`.
- **Anything else** (a key-value store, a secrets manager) gets its own package and implements the
  contract directly. Use `tests/support/memory_adapter.py` as a compact reference implementation.

## Checklist for a new adapter package

The steps below use a hypothetical `redis://` backend; `<name>` stands for its package name,
`redis`. Work test-first: each
step starts with the test that fails without it.

### 1. Tests first

Create `tests/adapters/<name>/` with an `__init__.py` and these modules:

- **`backend.py`:** a contract `Backend` whose `open(*, setup=...)` returns a **new, independent**
  adapter on the same storage at every call, plus a context manager that yields a fresh, empty
  backend and cleans it up. Copy the shape of `tests/adapters/sqlite/backend.py`.
- **`test_contract.py`:** plug into the shared suite. Override nothing but `make_backend`, and keep
  it a class-scoped classmethod fixture, because Hypothesis refuses function-scoped fixtures:

  ```python
  class TestRedisAdapterContract(AdapterContract):
      @pytest.fixture(scope="class")
      @classmethod
      @override
      def make_backend(cls, tmp_path_factory: pytest.TempPathFactory) -> BackendFactory:
          return lambda: redis_backend(...)
  ```

  The suite covers listing order, round-trips of tricky values and timestamps, racing creates and
  writes, stale and wrong revisions, invalid names, persistence across instances, read-only mode
  and closing. It opens several instances at once in threads (`_RACERS` in
  `tests/contract/adapter_contract.py`).
- **`test_url.py`:** the URL parser. Cover valid forms, rejected options, and that no error message
  contains a password.
- **`test_adapter.py`:** what the contract can't know: corrupt data, driver errors becoming
  `BackendError`, read-only details, timeouts, and redaction in `repr` and messages.
- **`test_package.py`:** the package re-exports, like `tests/adapters/files/test_package.py`.

### 2. The package

Create `src/environment_store/adapters/<name>/`:

- **`__init__.py`:** a docstring, the driver import (so a missing extra is detected), re-exports of
  the factory and the adapter class, and `__all__`.
- **`url.py`:** a pure parser.
  - It calls `scheme_of`, rejects options it would ignore, and raises `ValidationError` without
    echoing the URL.
  - Keep secrets in `field(repr=False)`.
- **`adapter.py`:** the factory and the class.

```python
def open_redis(url: str, /, *, setup: SetupMode = SetupMode.AUTO) -> "RedisAdapter":
    """Open a `redis://` backend.

    Args:
        url: The connection string.
        setup: `READ_ONLY` refuses every write and bounds every wait.

    Returns:
        The adapter.

    Raises:
        ValidationError: The connection string is not a valid `redis://` URL.
        BackendError: The server can't be reached.
    """
    return RedisAdapter(parse_url(url), setup=setup)


class RedisAdapter:
    """An `Adapter` that keeps each store as one hash in Redis."""

    def create_store(self, record: StoreRecord) -> None:
        """Create a new store; of two racing creates exactly one wins.

        Args:
            record: The new store, at revision 1.

        Raises:
            StoreExistsError: A store with this name exists.
            BackendError: The server failed.
        """
        check_create(record)
        check_writable(self._setup, location=self._target.location)
        ...  # atomic "create if absent"; map driver errors to BackendError

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        """Replace a store if its revision is still `expected_revision`.

        Args:
            record: The new content, at `expected_revision + 1`.
            expected_revision: The revision the caller read.

        Raises:
            ConcurrentModificationError: The store changed since it was read.
            StoreNotFoundError: The store does not exist.
            BackendError: The server failed.
        """
        check_write(record, expected_revision=expected_revision)
        check_writable(self._setup, location=self._target.location)
        ...  # compare-and-set on the revision in one atomic step

    @override
    def __repr__(self) -> str:
        """Name the location, never the connection string."""
        return f"RedisAdapter({self._target.location})"
```

Keep each module under about 400 lines. Split helpers (rows, schema, read-only settings) into their
own modules, as `adapters/postgres/` does.

### 3. Registry and configuration

- **`src/environment_store/core/connection.py`:**
  - Add the scheme to `ADAPTER_FACTORIES`, with `extra` and `requires` if it needs a driver.
  - Add a branch to `connection_location` if the default "the redis:// backend" isn't specific
    enough for messages.
- **`src/environment_store/config/project.py`:** if the scheme takes a relative path, teach
  `anchor_connection` to anchor it to the project file's directory, as it does for `json://`,
  `toml://` and `sqlite:///`.
- **Tests:** `tests/unit/core/test_connection.py` checks the full scheme list and the
  "unsupported scheme" message, so update both. Add the location branch to
  `tests/unit/core/test_connection_location.py`.

### 4. Import rules

Add a row for `adapters.<name>` to `ALLOWED_IMPORTS` in `tests/unit/test_import_direction.py`:
`core` and the package itself, plus `adapters.sql` for a SQL backend.
`test_every_package_and_adapter_subpackage_has_import_rules` fails until you do. Add the same row
to the table in [Architecture](architecture.md#layers-and-import-rules); a docs test compares them.

### 5. Optional extra (only for a third-party driver)

- **`pyproject.toml`:** add the extra under `[project.optional-dependencies]`, add the same
  requirement to `all` and to the `testing` dependency group, then run `uv lock`.
  `tests/unit/test_import_direction.py` and `tests/unit/test_package.py` import every module, so
  the driver must be installed in the development environment.
- **Missing-extra test:** add one to `tests/adapters/<name>/test_adapter.py`, following
  `tests/adapters/postgres/test_adapter.py::test_open_adapter_without_psycopg_asks_for_the_postgres_extra`.
  The generic mechanism is already covered in `tests/unit/core/test_connection.py`.

### 6. A server for the tests

A backend that needs a server follows the PostgreSQL pattern:

- **Throwaway server.** A fixture uses the disposable server named by an
  `ENV_STORE_TEST_<NAME>_URL` variable or, without it, starts a private server from local binaries
  that listens on no network port. It never uses a shared server.
- **Marker.** Register a marker in `[tool.pytest.ini_options] markers` and set it with `pytestmark`
  in every server-backed module. Add a guard like `tests/adapters/postgres/test_markers.py`.
- **CI.** Add a service container and the URL variable to the `test` job in
  `.github/workflows/ci.yml`.
- **Changelog.** Every `ENV_STORE_*` variable that `src/` reads must be named in `CHANGELOG.md`
  (`test_changelog_names_every_environment_variable_the_package_reads`). Test-only variables in
  `tests/` don't count.
- **CLI tests on the new backend (optional).** The `cli` fixture runs CLI tests on JSON, TOML and
  SQLite (`SCHEMES` in `tests/support/cli.py`). Add the new scheme there only if its backend is
  cheap to create for every test. Then also extend the `Scheme` literal and `connection_for` in
  `tests/support/cli.py`, and update
  `tests/cli/foundation/test_harness.py::test_schemes_are_json_toml_sqlite`.

### 7. Documentation

- **This guide.** Add a row to [The existing adapters](#the-existing-adapters) and the package to the
  [repository layout](architecture.md#repository-layout).
  `tests/docs/test_documentation.py::test_adapter_guide_names_every_registered_scheme` fails until
  every registered scheme appears in this page as `` `<scheme>://` ``.

No test lists the schemes in the user docs, so check each place yourself:

- **`docs/configuration.md`:** the backend overview table and a section of its own beside the
  existing backends. Update the list of supported schemes in the unsupported-scheme example, and the
  schema table if the backend has a schema.
- **`docs/cli.md`:** the connection string table, the unsupported-scheme example, the extras table
  and the install lines. Both unsupported-scheme examples, here and in `docs/configuration.md`, use
  `redis`; if that is the scheme you add, pick another sample.
- **`docs/python.md`:** the scheme table and the install lines.
- **`docs/installation.md`:** the extras table.
- **Other places:** `README.md`, `docs/README.md` (the "Concepts in one minute" list) and
  `docs/quickstart.md`.
- **The man page:** `docs/man/share/man/man1/envs.1`, the connection forms and `migrate`.
- **The agent skill:** `.claude/skills/environment-store-cli/SKILL.md` and `reference.md`.
- **`CHANGELOG.md`:** an entry under `## [Unreleased]`, `### Added`.

Then run the definition of done, including the new server tests.
