# environment-store CLI reference

Companion to [SKILL.md](SKILL.md). Checked against `envs --version` = `environment-store 2.0.0`.
The same reference is in the man page `envs(1)` (`docs/man/share/man/man1/envs.1` in the repository).
Every flag defaults to off; every option with a value defaults to none.

## Global options (before the command name)

After the command name they fail with exit 1 and a hint: `No such option: --noinput; --noinput is a
global option: put it before the command, e.g. envs --noinput ls`.

| Option | Meaning |
|---|---|
| `-c, --connection URL` | Connection string; overrides `ENV_STORE_CONNECTION` and `connection` in `.envstore.toml`. Must not be empty. Relative paths resolve against the current directory (same for `ENV_STORE_CONNECTION`). |
| `--no-project` | Ignore `.envstore.toml`. |
| `--noinput` | Never prompt: missing keys exit 4, missing confirmations (no `-y`) exit 1. Without a terminal the CLI already behaves this way. |
| `--version` | Print `environment-store <version>`. |
| `-h, --help` | Help; also `envs COMMAND -h` / `envs COMMAND --help`. Reads neither the connection nor `.envstore.toml`. |

Environment variables:

| Variable | Values |
|---|---|
| `ENV_STORE_CONNECTION` | connection string; empty = unset |
| `ENV_STORE_ORDERED_OVERWRITE` | `true` (last store wins, default) or `false` (first wins); also `1/0/yes/no`, case-insensitive |
| `ENV_STORE_KEY_<STORE>` | key line (`envstore-key-v1:...`, not base64) or passphrase of an existing encrypted store; `<STORE>` = store name upper-cased, `-` as `_`. One trailing newline stripped. Empty/invalid -> exit 4 (message names the variable, not the value). Ignored for plain and unused stores; never a new key. Two encrypted stores of one command mapping to one set variable (`my-app`, `my_app`) -> exit 1 unless `-k` covers both. `run` removes all `ENV_STORE_KEY_*` from the child |

Key precedence for an existing store: `-k` > `ENV_STORE_KEY_<STORE>` > `[keys]` > prompt (not with `--noinput`) > exit 4.

Merge order precedence: `--first-wins` > `ENV_STORE_ORDERED_OVERWRITE` > `ordered_overwrite` > last wins.
There is no `--last-wins` flag.

## Per-command options

### Reading: `ls`, `get`, `export`, `export-shell`, `run`

Positional `STORES...` in load order (default: `stores` in `.envstore.toml`; positional stores replace it).

Merged output order: store by store in load order, names sorted within a store, a name shared by
several stores at its first position with the winning value (`store-a`: `ENV`, `DEBUG`; `store-b`: `ENV`,
`DB_NAME` -> `DEBUG`, `ENV`, `DB_NAME`). Applies to `ls` (also `--json`), `export` (every format),
`export-shell` and `run`.

| Option | `ls` | `get` | `export` | `export-shell` | `run` | Meaning |
|---|---|---|---|---|---|---|
| `-k, --key STORE=PATH` | yes | yes | yes | yes | yes | Key/passphrase file per store, `STORE=-` for stdin; repeatable; bare `PATH` only with one store |
| `--first-wins` | yes | yes | yes | yes | yes | First store wins |
| `-v, --values` | yes | | | | | Show values (non-printable ones as JSON strings, e.g. `MULTI="a\nb"`) |
| `--source` | yes | | | | | Show the winning store |
| `--json` | yes | yes | | | | One JSON document |
| `-f, --file PATH\|-` | | | yes | | | Output file (mode 0600, created exclusively) |
| `-t, --type` | | | yes | | | `dotenv` (default on stdout), `json`, `toml`; else inferred from `-f` name |
| `--force` | | | yes | | | Replace an existing output file (atomically) |
| `--nested` | | | yes | yes | yes | No merge; `STORE__NAME` or one table per store |
| `-o, --overwrite` | | | | yes | yes | Override variables already set in the environment |

`run`: everything after the first `--` is the command, executed without a shell. The store
variables are added to the current environment; variables already set there win unless `-o`.
On POSIX `envs` replaces itself with the command. Every `ENV_STORE_KEY_*` variable is removed
from the command's environment. Options may come after the positional stores.

Encrypted stores need their key for every reading command, including names-only `ls`.

`get --json` prints an indented object (`name`, `store`, `value`) and a trailing newline; raw
`get` prints the value with no trailing newline when stdout is not a terminal.

`export-shell` prints one line per variable, values single-quoted for POSIX `sh` when needed
(`'it'"'"'s'`). Without `-o`: `[ -n "${A+x}" ] || export A=1` (keeps an existing `A`); with `-o`:
`export A=1`. It prints values, so use it inside `eval "$(...)"`.

### Writing: `set`, `rm`, `import`

| Option | `set` | `rm` | `import` | Meaning |
|---|---|---|---|---|
| `-s, --store STORE` | required | required | required | Store to change (never taken from the project file) |
| `-o, --overwrite` | yes | | yes | Replace existing variables (otherwise exit 3, nothing written) |
| `-k, --key PATH\|-` | yes | yes | yes | Key/passphrase file of the store |
| `-f, --file PATH\|-` | | | yes | Input; none or `-` reads stdin |
| `-t, --type` | | | yes | `dotenv` (stdin default), `json`, `toml` |

- `set KEY=VALUE...`: one write; value is everything after the first `=`; may be empty. Plaintext stores only.
- `set KEY`: value from stdin (piped, or `--noinput`), one trailing LF/CRLF stripped. Cannot be mixed with pairs or other bare keys. Empty stdin (zero bytes) is exit 1 and writes nothing; an empty value needs `echo | envs set -s S KEY` or `KEY=`.
- `set` and `import` never create a store: a missing store is exit 2 (`store 'x' not found in ...`).
- `import`: the store must exist. dotenv input is literal (`${X}` never expanded), python-dotenv grammar (`export` prefix, comments, quotes, escapes in double quotes). JSON/TOML must be a flat object of strings. Empty input prints `nothing to import into store 'x'` and exits 0.
- `rm KEY...`: all-or-nothing; any missing name -> exit 2, nothing deleted.

### Store lifecycle

| Command | Options |
|---|---|
| `ls-store` | `--json`; needs no key. An empty backend prints nothing on stdout (`[]` with `--json`), exits 0 and writes `no stores in <location>` to stderr |
| `create-store NAME` | `-e/--encrypt` plus exactly one of `-k PATH\|-` (existing key file), `--generate-key PATH` (new file), `--passphrase` |
| `rm-store NAME` | `-y/--yes`; needs no key |
| `cp-store SRC DST` / `mv-store SRC DST` | `--to URL` (other backend; DST may equal SRC there), `-k PATH\|-` (source key), and at most one of `--plain`, `--new-key PATH\|-`, `--generate-key PATH`, `--passphrase`. Default: same encryption and secret as the source |
| `encrypt -s STORE` | exactly one of `--new-key PATH` (existing key file), `--generate-key PATH` (new file), `--passphrase`. Rewrites the store in place; already encrypted -> exit 1, use `rekey`. Does not touch `.envstore.toml` |
| `rekey -s STORE` | `-k OLD` (else `ENV_STORE_KEY_<STORE>`, `[keys]`, prompt), plus exactly one of `--new-key`, `--generate-key`, `--passphrase` (can switch keyfile <-> passphrase; passphrases get a new salt) |
| `keygen PATH\|-` | writes a key file (0600, never overwrites) or prints the key with `-`; reads neither the connection nor the project file |
| `migrate` | SQL only; prints `created schema v1`, `upgraded schema from vN to vM` or `schema is up to date (v1)` |

`--passphrase` reads stdin when piped (one trailing newline stripped; empty -> exit 4); on a
terminal it asks twice. `--generate-key` writes mode 0600, never overwrites (exit 1,
`key file 'x' already exists; refusing to overwrite it`), refuses `-` and needs an existing parent
directory. `--new-key PATH` must name an existing file (missing -> exit 4). A new key or passphrase
read from stdin (`-k -` on `create-store`, `--new-key -`, piped `--passphrase`) is not saved by
`envs`: after success stderr warns `envs does not save this key; keep it, or store 'x' cannot be read
again` (`passphrase` for a passphrase).

## Shell completion

`envs completion bash|zsh|fish` prints a completion script on stdout and exits 0; like `keygen` it reads
neither the connection nor the project file. It is for the user's interactive shell, not for agents:
never add it to a start-up file unless the user asked. The lines to give the user (envs never edits these
files itself):

```sh
eval "$(envs completion zsh)"     # ~/.zshrc, after compinit
eval "$(envs completion bash)"    # ~/.bashrc; bash 4.4 or newer (macOS /bin/bash 3.2 fails: use a Homebrew bash)
envs completion fish > ~/.config/fish/completions/envs.fish
```

Run as `environment-store completion SHELL`, the script completes that name instead. It completes
commands, options, fixed values (`-t`, the shells), existing store names (never a new name: not for
`create-store` or the `cp-store`/`mv-store` target), variable names of plaintext stores for `get`, `rm`,
`set` (never of encrypted stores: no key is read) and paths (after `run ... --` only paths). It never prompts, never writes to stderr,
never creates a file, directory or schema, and offers nothing when the backend is missing, broken or slow.
Any other shell name is a usage error (exit 1).

Instead of the `eval` line the user can save the script once as a file (faster shell start; rerun after
upgrading). The same rule applies: never write these files or edit `plugins=(...)` unless the user asked.
zsh autoloads it as `_envs` from any `fpath` directory added before `compinit` (its first line is
`#compdef envs`); for Oh My Zsh that is `$ZSH_CUSTOM/plugins/envs/_envs` plus `envs` in `plugins=(...)`.
bash-completion 2 loads `${XDG_DATA_HOME:-~/.local/share}/bash-completion/completions/envs` on demand.
For `environment-store` replace every `envs` in these names. Details: the repository's `docs/cli.md`,
section "Saving the script as a file".

## Project file `.envstore.toml`

- Found by walking up from the current directory; the first regular file wins.
- Ignored with a warning when not owned by you or root, or world-writable.
- `envs` never writes it: add `[keys]` entries yourself after `create-store -e` or `encrypt`.
- Only keys `connection`, `stores`, `ordered_overwrite`, `[keys]`; anything else is an error (exit 1) that breaks every command except `keygen`, `completion`, `-h`/`--help` and `--version` (they do not read the file).
- Relative `json://`, `toml://`, `sqlite:///` connections and `[keys]` paths are relative to the project file's directory.
- `[keys]` holds paths only, never key material. A `[keys]` entry for a plaintext store that a command loads is an error.
- A password in `connection` prints a warning on every command that reads the file; put such connections in `ENV_STORE_CONNECTION`.

## Backends

| Scheme | Notes |
|---|---|
| `json://DIR`, `toml://DIR` | One `<store>.json`/`.toml` per store plus `.<store>.<ext>.lock`, files mode 0600; dir created on first write (mode 0700); `~` expanded; no `?`/`#` |
| `sqlite:///rel.db`, `sqlite:////abs.db`, `sqlite:///~/x.db` | File (mode 0600, also `-wal`/`-shm`), schema and upgrades handled automatically (no `migrate` needed); `~` expanded; missing parent dir created on first write (mode 0700) |
| `postgresql://` / `postgres://` | Needs `environment-store[postgres]`. `?schema=NAME` (default `environment_store`). Percent-encode `@ / ?` in credentials. Older schema -> run `envs migrate`. Missing CREATE privilege on first setup -> an admin runs `envs migrate` once |

## dotenv output rules

`export` writes `KEY=VALUE` that python-dotenv and Docker Compose both read back exactly:
unquoted for `[A-Za-z0-9_./:@%+,-]`, else single quotes, else double quotes with escapes.
Values containing `${`, or needing double quotes and containing `$`, are refused (exit 1):
export them with `-t json` / `-t toml`, or use `envs run`.

## Exit codes

| Code | Error classes |
|---|---|
| 1 | ValidationError (incl. AlreadyEncrypted, NotEncrypted, PlaintextNotAllowed), ConfigurationError, MissingExtraError, BackendError, usage errors, refused confirmation |
| 2 | StoreNotFoundError, VariableNotFoundError (a missing store is reported before a missing variable) |
| 3 | StoreExistsError, VariableExistsError |
| 4 | KeyRequiredError, DecryptionError, InvalidKeyFileError, KeyModeMismatchError, KeySourceError |
| 5 | ConcurrentModificationError (rerun) |
| 126 / 127 | `run`: not executable / not found; otherwise `run` returns the command's code |
