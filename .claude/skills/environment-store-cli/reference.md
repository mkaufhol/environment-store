# environment-store CLI reference

Companion to [SKILL.md](SKILL.md). Checked against `envs --version` = `environment-store 2.0.0.dev0`.
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
| `--help` | Help; also `envs COMMAND --help`. |

Environment variables (the only two read; there are none for keys):

| Variable | Values |
|---|---|
| `ENV_STORE_CONNECTION` | connection string; empty = unset |
| `ENV_STORE_ORDERED_OVERWRITE` | `true` (last store wins, default) or `false` (first wins); also `1/0/yes/no`, case-insensitive |

Merge order precedence: `--first-wins` > `ENV_STORE_ORDERED_OVERWRITE` > `ordered_overwrite` > last wins.
There is no `--last-wins` flag.

## Per-command options

### Reading: `ls`, `get`, `export`, `export-shell`, `run`

Positional `STORES...` in load order (default: `stores` in `.envstore.toml`; positional stores replace it).

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
On POSIX `envs` replaces itself with the command. Options may come after the positional stores.

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
| `rekey -s STORE` | `-k OLD`, plus exactly one of `--new-key`, `--generate-key`, `--passphrase` (can switch keyfile <-> passphrase; passphrases get a new salt) |
| `keygen PATH\|-` | writes a key file (0600, never overwrites) or prints the key with `-`; reads neither the connection nor the project file |
| `migrate` | SQL only; prints `created schema v1`, `upgraded schema from vN to vM` or `schema is up to date (v1)` |

`--passphrase` reads stdin when piped (one trailing newline stripped; empty -> exit 4); on a
terminal it asks twice. `--generate-key` writes mode 0600, never overwrites (exit 1,
`key file 'x' already exists; refusing to overwrite it`), refuses `-` and needs an existing parent
directory. `--new-key PATH` must name an existing file (missing -> exit 4). A new key or passphrase
read from stdin (`-k -` on `create-store`, `--new-key -`, piped `--passphrase`) is not saved by
`envs`: after success stderr warns `envs does not save this key; keep it, or store 'x' cannot be read
again` (`passphrase` for a passphrase).

## Project file `.envstore.toml`

- Found by walking up from the current directory; the first regular file wins.
- Ignored with a warning when not owned by you or root, or world-writable.
- `envs` never writes it: add `[keys]` entries yourself after `create-store -e` or `encrypt`.
- Only keys `connection`, `stores`, `ordered_overwrite`, `[keys]`; anything else is an error (exit 1) that breaks every command except `keygen`, `--help` and `--version` (they do not read the file).
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
