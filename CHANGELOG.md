# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/) (pre-release versions follow PEP 440).

## [Unreleased]

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

[Unreleased]: https://github.com/mkaufhol/environment-store/compare/v0.1.0rc2...HEAD
[0.1.0rc2]: https://github.com/mkaufhol/environment-store/compare/v0.1.0rc1...v0.1.0rc2
[0.1.0rc1]: https://github.com/mkaufhol/environment-store/releases/tag/v0.1.0rc1
