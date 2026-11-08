# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/) (pre-release versions follow PEP 440).

## [Unreleased]

## [2.0.0] - 2026-11-08

Version 2 is a rewrite and not compatible with 0.1: the data model, the Python API and the command line all
changed, and there is no migration path from 0.1 stores. The
[documentation](https://github.com/mkaufhol/environment-store/blob/main/docs/README.md) describes 2.0.

### Added

- **Named stores**: flat collections of `NAME=value` pairs (`base`, `dev`, `customer-a`), loaded and merged in any
  combination. Store names are 1 to 63 lowercase letters, digits, `_` or `-`, starting with a letter.
- **Backends** selected by a connection string from `-c/--connection`, `ENV_STORE_CONNECTION` or `connection` in
  the project file: `json://dir` and `toml://dir` (one file per store), `sqlite:///file.db` and
  `postgresql://...` (`postgres` extra). SQL schemas are created on first use and upgraded with `envs migrate` /
  `EnvironmentStore.migrate()`. Writes are checked against the store's revision, so concurrent writers cannot
  silently overwrite each other.
- **Encryption per store**: AES-256-GCM over all names and values together, with a random key file
  (`envs keygen`, mode `0600`, never overwritten) or an Argon2id passphrase. Keys come from `-k PATH`,
  `-k STORE=PATH`, stdin (`-k -`), the project file, a prompt, or `ENV_STORE_KEY_<STORE>` for deployments
  (Heroku, Kubernetes, CI); `envs run` removes the key variables from the child's environment.
- **Python library**: `environment_store.load("base", "dev")` merges stores into `os.environ` like `load_dotenv()`
  and resolves settings like the CLI; `EnvironmentStore` manages stores and variables (create, copy, move, delete,
  encrypt, rekey, migrate, also across backends); `Environment` gives the merged variables, their sources, nested
  views, `apply()`, `dumps()` and `to_file()`. Fully typed (`py.typed`); all errors derive from
  `EnvironmentStoreError`, and a missing extra raises `MissingExtraError` naming the install command.
- **`envs` command line tool** (`cli` extra, also installed as `environment-store`), with 19 commands:
  - stores: `ls-store`, `create-store`, `rm-store`, `cp-store`, `mv-store`;
  - variables: `ls`, `get`, `set`, `rm`, `import`;
  - loading: `export`, `export-shell`, `run`;
  - keys: `keygen`, `rekey`, `encrypt`;
  - other: `migrate`, `tui`, `completion`.
- **Merge order**: the last store wins by default; `--first-wins`, `ENV_STORE_ORDERED_OVERWRITE=false` or
  `ordered_overwrite = false` in the project file pick first-wins. Merged variables are listed store by store in load
  order, each store's names sorted; `--source` shows which store each value comes from.
- **Import and export** in dotenv, JSON and TOML (also nested per store), plus `export-shell` for `eval` in POSIX
  shells. Exported `.env` files read back exactly with python-dotenv and Docker Compose; values that cannot be
  written safely are refused.
- **Project file** `.envstore.toml`: connection, default stores, key files and merge order for a directory tree,
  used only when its owner and permissions pass a trust check.
- **Scripting**: data on stdout, messages on stderr, `--json` output, stable exit codes 0 to 5 (`run` returns the
  command's own exit code, or 126/127 when it cannot start it), `--noinput` for CI, `-h` as a shorthand for
  `--help` on every command.
- **Terminal UI** (`envs tui`, `tui` extra): browse, create (with every encryption option), remove and export
  stores; add, edit and delete variables with values masked; path completion in path inputs; each screen's keys
  in its footer.
- **Shell completion** for bash, zsh and fish (`envs completion SHELL`): commands, options, store names, variable
  names of plaintext stores and paths. Completion only reads and never asks for a key.
- **Reference pages**: the wheel installs the `envs(1)` man page (also as `environment-store(1)`); the repository
  has a tldr page and an agent skill for coding agents that drive the CLI.

### Changed

- Rebuilt from scratch: named stores instead of the organisation / project / environment / service hierarchy.
- Requires Python 3.13 or newer. The core depends on `cryptography` only; PostgreSQL, CLI and TUI are extras
  (`postgres`, `cli`, `tui`, `all`).

### Removed

- All V1 code, tests and docs: the hierarchy model, the JSON file, PostgreSQL (SQLAlchemy / yoyo) and AWS
  adapters, the V1 CLI, TUI and agent skill (replaced, see Added) and the tox setup.
- The extras `aws` and `full`; install `environment-store[all]` (or `cli`, `tui`, `postgres`) instead. AWS
  adapters may return after 2.0.
- The V1 changes below were never released and are dropped with V1:
  - `environment-store export-dotenv` writes the resolved variables of a level to a `.env` file
    (`--file` sets the path or name, default `./.env`; `--force` overwrites an existing file).
  - `environment-store levels` (alias `tree`) shows the existing levels as a tree, as `paths` or as nested `json`;
    `-o`/`-p`/`-e` and `--depth` limit it to part of the hierarchy.
  - Commands that work on a level open an interactive tree picker when they get none of `-o`/`-p`/`-e`/`-s` and run
    on a terminal. `--root` picks the root level without asking; without a terminal nothing changes.
  - `--no-interaction` (or `ENVIRONMENT_STORE_NO_INTERACTION=1`) makes the CLI never prompt, as if there were no
    terminal: no level picker, no `delete` confirmation, and `delete-level` requires `--confirm`.
  - `-h` explains the hierarchy options in detail and shows examples of addressing each level.

### Security

- Keys and passphrases are never stored or cached, never accepted as literal command line text, and never appear
  in logs, error messages or `repr`s; secret values are masked in the TUI.
- Key files are created with mode `0600` and refused if they already exist; store files, SQLite databases and
  exported files are created with mode `0600`.
- PostgreSQL access uses parameterised SQL only, and the schema name is validated and quoted.

## [0.1.0rc2] - 2026-10-15

### Added

- `environment-store export` prints the resolved variables of a level as shell code for `eval`
  (`--unset` removes them again).
- `EnvironmentStoreManager.load_into_environ()` loads the resolved variables of a level into
  `os.environ`, like `dotenv.load_dotenv`.

### Changed

- **Breaking:** the AWS Secrets Manager backend stores the whole store in a single secret named
  after the prefix (default `environment-store`) instead of one secret per hierarchy level.
  Variables are keyed by their path, e.g. `acme/webapp/dev/api/DB_HOST`. This cuts the number
  of billed secrets to one per store, but the store is limited to 64 KiB. Level secrets
  written by 0.1.0rc1 are no longer read; root level variables keep working unchanged.

## [0.1.0rc1] - 2026-10-14

First public pre-release.

### Added

- `EnvironmentStoreManager` Python API for hierarchical environment variables
  (organisation > project > environment > service).
- Storage backends: JSON file, PostgreSQL, AWS Systems Manager Parameter Store and
  AWS Secrets Manager.
- `environment-store` command line interface, including import, export and
  `transfer` between backends.
- Terminal UI (`environment-store[tui]`) built on Textual.
- Optional extras: `aws`, `postgres`, `tui` and `full`.
- Agent skill for using the CLI safely.

[Unreleased]: https://github.com/mkaufhol/environment-store/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/mkaufhol/environment-store/compare/v0.1.0rc2...v2.0.0
[0.1.0rc2]: https://github.com/mkaufhol/environment-store/compare/v0.1.0rc1...v0.1.0rc2
[0.1.0rc1]: https://github.com/mkaufhol/environment-store/releases/tag/v0.1.0rc1
