# Developer guide

This guide is for people and coding agents who change Environment Store itself. It explains how the
code is organised, why it is organised that way, and what to touch when you extend it.

**[`CONTRIBUTING.md`](../../CONTRIBUTING.md) is binding.** It lists the rules: test-driven
development, type hints everywhere, 100 % line and branch coverage, and the definition of done. This
guide doesn't repeat the rules. It shows how to follow them in this code base, and which tests catch
you when you don't.

## What Environment Store is

Environment Store keeps environment variables in named **stores** (`base`, `dev`, `prod`), plain or
encrypted, in a **backend** chosen by a connection string: JSON or TOML files, SQLite or PostgreSQL.
Reading commands combine several stores in load order, so `dev` can override `base`.

The project ships three frontends over one implementation:

- **The Python library**, `import environment_store`. Apps load their variables at startup with
  `environment_store.load(...)`.
- **The CLI**, `envs` (also installed as `environment-store`), with the `cli` extra.
- **The terminal UI**, `envs tui`, with the `tui` extra (and `cli`, because it runs through `envs`).

What the project values, in order:

1. **Secrets never leak.** No key, passphrase or decrypted value appears in a log, an error
   message, a `repr` or a traceback. An encrypted store is one sealed blob, so even variable names
   stay hidden.
2. **One implementation of every rule.** A validation, a merge order or a key-precedence rule lives
   in exactly one place, and every frontend calls it.
3. **A small core.** The core depends on `cryptography` only. Every other dependency is an
   optional extra that is imported only when it is used.
4. **Executable documentation.** The docs, the man page, the tldr page and the agent skill are
   checked against the real CLI by tests (see [Documentation](documentation.md)).

The user documentation starts at [`docs/README.md`](../README.md). Read the
[Quickstart](../quickstart.md) once before you change anything: it shows the behaviour you are about
to work on.

## Set up a development environment

You need [uv](https://docs.astral.sh/uv/) and, for the PostgreSQL tests, the PostgreSQL server
binaries `initdb` and `pg_ctl` on your `PATH`. Installing PostgreSQL is not always enough:

- **Homebrew:** `brew install postgresql@16` is keg-only, so also add
  `$(brew --prefix postgresql@16)/bin` to `PATH`.
- **Debian and Ubuntu:** `apt install postgresql` puts the binaries in
  `/usr/lib/postgresql/<version>/bin`; add that directory to `PATH`.

 Unless `ENV_STORE_TEST_POSTGRES_URL` is set, the tests start their own
throwaway cluster and never touch a server you already run. [Testing](testing.md#postgresql) explains the alternatives.

```bash
git clone https://github.com/mkaufhol/environment-store.git
cd environment-store
uv sync --locked              # every tool, every extra's dependency and the envs command
uv run pre-commit install     # run ruff, ty and bandit on every commit
git switch -c my-change main  # one branch per change, off main
```

Then run the definition of done from [`CONTRIBUTING.md`](../../CONTRIBUTING.md#1-toolchain) once.
When it passes on a clean checkout, your environment is right. [Tools](tooling.md) explains each
command.

## The guide

| Page | Read it when you want to… |
|---|---|
| [Architecture](architecture.md) | understand the layers, the allowed import directions, and how a command flows from the CLI to a backend |
| [Code conventions](conventions.md) | write code that passes review and the linters: value objects, errors, secrets, suppression comments |
| [Testing](testing.md) | find the right test file, use the fakes and fixtures, run part of the suite, keep 100 % coverage |
| [Tools](tooling.md) | understand uv, ruff, ty, bandit, pre-commit, CI and the release workflow |
| [Adding a storage adapter](adapters.md) | support a new backend, such as a new connection scheme |
| [Extending the CLI, the TUI and the library](extending.md) | add a command, an option, a TUI screen, an error class, a public name or an environment variable |
| [Keeping the documentation in sync](documentation.md) | know which documents a change touches and which tests check them |

## The workflow for every change

1. Branch off `main`.
2. Write a failing test that names the behaviour. Run it and watch it fail for the right reason.
3. Write the least code that makes it pass, then clean up with all tests green.
4. Update the documentation the change touches ([Documentation](documentation.md) lists where), and
   add an entry under `## [Unreleased]` in `CHANGELOG.md` if users can notice the change.
5. Run the definition of done. Coverage must stay at 100 %.
6. Commit in small steps, each with an imperative subject line and a body that says why.

## For coding agents

- [`CLAUDE.md`](../../CLAUDE.md) and [`CONTRIBUTING.md`](../../CONTRIBUTING.md) apply to you.
  Run the full definition of done before you report work as finished.
- Before you add a module, find its layer in [Architecture](architecture.md#layers-and-import-rules).
  The import rules are tested, and a lazy or type-only import still counts.
- Follow the checklists in [Adding a storage adapter](adapters.md) and [Extending](extending.md)
  step by step. Each step names the test that fails if you skip it.
- Don't point comments or docstrings at documents, issues or plans. Explain the reason in place.
- `.claude/skills/environment-store-cli/` is the skill for *using* the `envs` CLI. It is user
  documentation that you keep in sync, not instructions for developing this repository.
