<p align="center">
  <img src="assets/environment-store-logo.svg" alt="Environment Store logo" width="120">
</p>

# Environment Store documentation

New here? Start with the [Quickstart](quickstart.md). It takes about ten minutes and every command in it was run
against the real CLI.

## Guides

| Guide | Read it when you want to… |
|---|---|
| [Quickstart](quickstart.md) | try the tool from scratch: plain and encrypted stores, `.env` export, `envs run`, Python |
| [Installation](installation.md) | install the CLI, the library, PostgreSQL support or the TUI |
| [CLI reference](cli.md) | look up a command, an option, an output format or an exit code |
| [Python library](python.md) | load stores from Python or manage them programmatically |
| [Configuration](configuration.md) | choose a backend, write `.envstore.toml`, use `ENV_STORE_CONNECTION` in CI |
| [Encryption and keys](encryption.md) | encrypt a store, use key files or passphrases, rotate or remove encryption |
| [Terminal UI](tui.md) | browse and edit variables interactively with `envs tui` |
| [Agent skill](../.claude/skills/environment-store-cli/SKILL.md) | let a coding agent use the `envs` CLI safely |

## How do I…

| Task | Where to look |
|---|---|
| install it? | [Installation](installation.md) (2.0 is not on PyPI yet; install from source) |
| create a store and add variables? | [Quickstart](quickstart.md#2-create-a-plain-store), [`envs set`](cli.md#envs-set--set-variables) |
| bring in an existing `.env`, JSON or TOML file? | [`envs import`](cli.md#envs-import--fill-a-store-from-a-file) |
| keep secrets encrypted? | [Quickstart](quickstart.md#4-create-an-encrypted-store), [Encryption and keys](encryption.md) |
| encrypt a store that is plain today? | [`envs encrypt`](cli.md#envs-encrypt--encrypt-a-plain-store), [recipe](cli.md#encrypt-an-existing-plain-store) |
| create a key file or rotate a key? | [`envs keygen`](cli.md#envs-keygen--create-a-key-file), [`envs rekey`](cli.md#envs-rekey--change-a-stores-key), [recipe](cli.md#rotate-a-key) |
| delete variables? | [`envs rm`](cli.md#envs-rm--delete-variables) |
| delete a store? | [`envs rm-store`](cli.md#envs-rm-store--delete-a-store) |
| rename or copy a store, or move it to another backend? | [`envs mv-store` / `envs cp-store`](cli.md#envs-cp-store-and-envs-mv-store--copy-rename-move-decrypt), [recipe](cli.md#back-up-or-move-stores-to-another-backend) |
| combine `base` and `dev` so `dev` wins? | [Quickstart](quickstart.md#5-combine-stores), [combining stores](cli.md#combining-several-stores) |
| write a `.env` file for Docker Compose? | [Quickstart](quickstart.md#6-export-a-env-file), [`envs export`](cli.md#envs-export--write-dotenv-json-or-toml) |
| start my app with the variables? | [Quickstart](quickstart.md#7-run-a-command-with-the-variables), [`envs run`](cli.md#envs-run--run-a-command-with-the-variables) |
| load variables in Python? | [Quickstart](quickstart.md#8-use-the-variables-in-python), [Python library](python.md) |
| stop typing `-c` and `-k` every time? | [Quickstart](quickstart.md#9-save-your-settings-in-a-project-file), [Configuration](configuration.md#the-project-file-envstoretoml) |
| use PostgreSQL? | [Installation](installation.md#optional-extras), [Configuration](configuration.md#postgresql) |
| create or upgrade the SQL schema? | [`envs migrate`](configuration.md#upgrade-the-sql-schema-envs-migrate) |
| run it in CI without prompts? | [CI recipe](cli.md#ci-no-prompts-key-from-a-secret), [CLI reference](cli.md#exit-codes) (`--noinput`, exit codes) |

## Concepts in one minute

- A **store** is a named, flat set of variables, for example `base`, `dev`, `prod` or `customer-a`. Store names
  use 1 to 63 lowercase letters, digits, `_` and `-`, and start with a letter.
- A **variable** has a POSIX name (`DB_HOST`, `_private`, case-sensitive) and any UTF-8 text as its value,
  including empty and multi-line values.
- A **backend** is where stores live. You choose it with a **connection string**: `json://dir`, `toml://dir`,
  `sqlite:///file.db` or `postgresql://user@host/db`.
- A store is either **plain** or **encrypted** as a whole, with a **key file** or a **passphrase**.
- Reading commands take several stores in **load order**. By default the last store wins when two define the same
  variable.
