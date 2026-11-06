# Encryption and keys

environment-store can encrypt a store so that its contents are useless without a key. This page explains when to
use encryption, how keys work, how to hand them to `envs` (also in CI), and how to rotate or remove encryption.

Every command on this page was run against the real CLI. The examples use `-c json://envs`; any backend works the
same way. To keep them short, the connection is omitted after the first few examples. Set
`ENV_STORE_CONNECTION=json://envs` or use a [project file](configuration.md#the-project-file-envstoretoml) to do
the same.

- [When to encrypt](#when-to-encrypt)
- [What is protected, and what is not](#what-is-protected-and-what-is-not)
- [Key file or passphrase?](#key-file-or-passphrase)
- [Create a key file: `envs keygen`](#create-a-key-file-envs-keygen)
- [Create an encrypted store](#create-an-encrypted-store)
- [Give the key to a command](#give-the-key-to-a-command)
- [Write secrets safely](#write-secrets-safely)
- [Encrypt, rotate, copy and decrypt](#encrypt-rotate-copy-and-decrypt)
- [Which commands need a key](#which-commands-need-a-key)
- [Key errors and exit codes](#key-errors-and-exit-codes)
- [If you lose the key](#if-you-lose-the-key)

## When to encrypt

Encrypt a store when it holds anything you would not paste into a chat: database passwords, API tokens, signing
keys. Plain stores are fine for settings like `LOG_LEVEL` or `DB_HOST`.

A common setup is a plain `base` store plus encrypted `staging` and `prod` stores, loaded together:

```sh
envs run base prod -k prod=~/.keys/prod.key -- ./manage.py migrate
```

Encryption is worth it especially when the stores live somewhere shared: a database that other people or services
can read, a backup, or a synced folder. Anyone who can read the file or table still sees only ciphertext.

## What is protected, and what is not

A store is either plain or encrypted **as a whole**. For an encrypted store, all variable names and values are
serialised together and encrypted as one blob with **AES-256-GCM**.

| Hidden without the key | Visible to anyone who can read the backend |
|---|---|
| variable names | the store name |
| variable values | that the store is encrypted, and its key mode (`keyfile` or `passphrase`) |
| how many variables there are | the passphrase settings (Argon2id parameters and salt) |
| | creation and last-change timestamps, and the revision (number of writes) |
| | the approximate size of the contents (the ciphertext grows with the data) |

This is what an encrypted store looks like on disk (`envs/prod.json`):

```json
{
  "format": 1,
  "encrypted": true,
  "revision": 2,
  "created_at": "2026-11-06T16:37:41.495584Z",
  "updated_at": "2026-11-06T16:37:41.618057Z",
  "payload": "oa3k2TCI6Tcx3+F7q4lOhkBQF7/+dXYmy/EdoQtEZH3BW5v0goljuzeyZ4ax0DQLK3U/DuWYZ7VKGfJoiy/x8ppPhA==",
  "cipher": {
    "name": "aes256gcm",
    "mode": "keyfile"
  }
}
```

`envs ls-store` shows which stores are encrypted, without a key and without a variable count:

```console
$ envs -c json://envs ls-store
name  encryption
base  plain
prod  encrypted (keyfile)
```

More details:

- Every write uses a fresh random 96-bit nonce, so writing the same data twice gives different ciphertext.
- The ciphertext is bound to the store name and its cipher settings. Copying one store's payload into another
  store, or editing the cipher settings, makes decryption fail instead of returning wrong data. A side effect:
  renaming or copying an encrypted store re-encrypts it, so `mv-store` and `cp-store` need the key.
- A wrong key never produces garbage. It fails with exit code 4:
  `Error: cannot decrypt store 'dev': wrong key or passphrase, or the stored data was modified`.
- The same message appears if someone tampered with the stored data. GCM authentication detects that.
- The tool never stores, caches or remembers a key. There are no environment variables for keys, and you cannot
  type a key directly on the command line, because it would end up in your shell history and in `ps` output.
- Error messages never contain values, keys or passphrases, with one exception you cause yourself: text in
  `[keys]` that is not a key-file line is treated as a path and printed in the "cannot read key file" error. So
  never put a passphrase in `[keys]` (see [below](#in-the-project-file-keys)).

What encryption does **not** protect:

- Values once they are loaded. `envs run`, `envs export` and `envs get` hand out plaintext on purpose. An exported
  `.env` file is plain text (written with mode `0600`), so treat it like a secret.
- A key file that sits next to the data. If an attacker can read both, encryption gains nothing. Keep key files out
  of the repository, out of the stores directory, and out of shared backups.
- Deleting a store. `envs rm-store` needs no key, so anyone with write access to the backend can delete an
  encrypted store. Use backend permissions and backups for that.

## Key file or passphrase?

Each encrypted store uses one of two key modes:

| | Key file (`keyfile`) | Passphrase (`passphrase`) |
|---|---|---|
| The secret | a random 256-bit key in a small file | text you can remember or keep in a password manager |
| Create with | `--generate-key PATH` or `-k PATH` / `--new-key PATH` | `--passphrase` |
| Strength | always full strength | as strong as the passphrase; stretched with Argon2id |
| Speed | instant | a short, deliberate delay per unlock (Argon2id, 64 MiB memory) |
| Good for | CI, servers, deploy secrets | people who unlock a store by hand |

Passphrases are stretched with **Argon2id** (3 iterations, 64 MiB memory, 4 lanes, 16-byte random salt). The salt
is stored with the store and changes on every `rekey`.

You can switch a store between the two modes at any time with [`envs rekey`](#rotate-a-key-envs-rekey).

## Create a key file: `envs keygen`

```console
$ envs keygen prod.key
wrote key file 'prod.key'
$ ls -l prod.key
-rw-------  1 me  staff  60 Nov  6 17:37 prod.key
$ cat prod.key
envstore-key-v1:xl9fQV1CJf3cWZYE7jDaFb0_fOsfyi6DOjUCJtP07wY
```

- The file is created with mode `0600`, so only you can read it.
- `keygen` never overwrites a file:

  ```console
  $ envs keygen prod.key
  Error: key file 'prod.key' already exists; refusing to overwrite it
  ```

- `keygen` needs no connection.

**Key file format.** One line: `envstore-key-v1:` followed by the 32-byte key in unpadded base64url (43
characters), and a newline. Whitespace around it is ignored when reading. The prefix lets `envs` tell a key file
from a passphrase file and give a clear error when you mix them up.

**Print a key instead of writing a file.** `envs keygen -` prints a new key, for example to save it straight into a
password manager:

```console
$ envs keygen -
envstore-key-v1:EuIabZkvpEgEF_ohr4afsBFj77r4Vxjj2qOpr4WSq1M
```

Save that line somewhere safe **before** you encrypt a store with it.

## Create an encrypted store

Add `-e` / `--encrypt` and exactly one way to get the key:

```console
$ envs -c json://envs create-store prod -e --generate-key prod.key     # write a new key file
created store 'prod'
$ envs -c json://envs create-store staging -e -k staging.key           # use an existing key file
created store 'staging'
$ printf 'correct horse battery staple\n' | envs -c json://envs create-store customer-a -e --passphrase
created store 'customer-a'
```

| Option | Meaning |
|---|---|
| `--generate-key PATH` | write a new key file to `PATH` (mode `0600`, never overwritten) and use it. The parent directory must exist |
| `-k PATH` | use an existing key file. `-k -` reads it from stdin |
| `--passphrase` | use a passphrase: read from stdin when piped (one trailing newline is removed), otherwise asked twice at a hidden prompt |

A key option without `-e`, `-e` without a key option, or more than one key option is refused (exit code 1):

```text
Error: -k, --generate-key and --passphrase encrypt the new store: add -e/--encrypt
Error: use only one of -k, --generate-key, --passphrase
Error: an encrypted store needs one of -k <path>, --generate-key <path>, --passphrase
Error: --generate-key needs a file path; to print a new key use 'envs keygen -' and pass it with '-k -'
```

On a terminal, `--passphrase` asks:

```text
New passphrase:
Repeat to confirm:
```

If the two entries differ, it asks again, up to three times. Both prompts go to stderr and nothing is echoed.

## Give the key to a command

Every command that reads or writes the contents of an encrypted store needs its key. `envs` looks for it in this
order:

1. `-k` on the command line
2. `[keys]` in the project file `.envstore.toml`
3. a hidden prompt, if stdin is a terminal and `--noinput` is not set
4. otherwise the command fails with exit code 4

`-k` always takes a **path**, never the key itself. The store's key mode decides how the file is read:

- for a `keyfile` store, the file is a key file made by `keygen`;
- for a `passphrase` store, the file holds the passphrase as UTF-8 text. Exactly one trailing newline (LF or CRLF)
  is removed; an empty passphrase is refused.

`~` and `~/…` in `-k` values are expanded.

### One store: `-k PATH`

```console
$ envs ls prod -k prod.key -v
DB_PASSWORD=hunter2
$ printf 'correct horse battery staple\n' > customer-a.pass && chmod 600 customer-a.pass
$ printf 'https://a.example.com\n' | envs set -s customer-a API_URL -k customer-a.pass
set API_URL in store 'customer-a'
$ envs ls customer-a -k customer-a.pass -v
API_URL=https://a.example.com
```

`customer-a` is a passphrase store, so `customer-a.pass` holds the passphrase as text.

### Several stores: `-k STORE=PATH`

When a reading command (`ls`, `get`, `export`, `export-shell`, `run`) loads several stores, bind each key to its
store by name. Repeat `-k` for each encrypted store; plain stores need nothing.

```console
$ envs ls base prod -k prod=prod.key -v
DB_HOST=localhost
DB_PASSWORD=hunter2
DB_PORT=5432
$ envs ls base prod -k prod.key
Error: -k <path> without a store name works with exactly one store; with several stores bind each key by name: -k <store>=<path>
```

`-k STORE=PATH` is read as a store binding only when the text before the first `=` is a valid store name.
Otherwise the whole value is a path, so `-k ./a=b.key` is the file `./a=b.key`.

Writing commands (`set`, `rm`, `import`, `rekey`, `cp-store`, `mv-store`) work on one store and take a plain
`-k PATH`. `encrypt` has no `-k`: the store is still plain, so there is no current key, and you give the new key
with `--new-key`, `--generate-key` or `--passphrase`.

### From stdin: `-k -` or `-k STORE=-`

`-` reads the key or passphrase from stdin. This is the way to use a password manager without a key file on disk:

```console
$ cat prod.key | envs get DB_PASSWORD prod -k -
hunter2
```

```sh
# 1Password, as an example
op read 'op://Private/envs prod/key' | envs run base prod -k prod=- -- ./deploy.sh
```

Stdin can be read only once per command, so only one store per command can get its key this way, and you cannot
pipe a value and a key at the same time:

```text
Error: only one -k may read from stdin ('-'); stdin can be read once
Error: stdin can be used only once per command: it is already used for the value of DB_PASSWORD, so it cannot be used for -k -
```

### In the project file: `[keys]`

List the key file or passphrase file for each encrypted store, and you never need `-k` in that project:

```toml
connection = "json://envs"
stores = ["base", "prod"]

[keys]
prod = "keys/prod.key"
```

```console
$ envs ls -v --source
DB_HOST=localhost    base
DB_PASSWORD=hunter2  prod
DB_PORT=5432         base
```

- Relative paths are resolved from the directory of `.envstore.toml`; `~` is expanded.
- A key-file line (`envstore-key-v1:…`) pasted into the file is refused:
  `[keys] entry for store 'prod' holds key material: paths only, never key material`.
  Any other text is taken as a path.
- **Never put a passphrase in `[keys]`.** It is not detected: it is treated as a file name, and the error shows it
  on stderr (`Error: cannot read key file '/…/correct horse battery staple': No such file or directory`). Put the
  passphrase in a file with mode `0600` and list the path of that file.
- A `-k` on the command line beats the `[keys]` entry for that store.
- An entry for a store that is not encrypted is an error once a command loads that store, and that includes every
  write to it (`set`, `rm`, `import`):
  `names a key for store 'base', which is not encrypted: remove the entry`.
- So add the entry only **after** `envs encrypt`, and update it after `envs rekey` or `--generate-key`. `encrypt`
  itself never reads `[keys]`.
- Commit the paths if you like, but **never commit the key files**. Add them to `.gitignore`.

See [Configuration](configuration.md#the-project-file-envstoretoml) for the rest of the project file.

### The prompt, and `--noinput` for scripts and CI

On a terminal, without `-k` or `[keys]`, `envs` asks with a hidden prompt on stderr:

```text
Key or passphrase for store 'prod':
```

Type the passphrase, or paste the key line (`envstore-key-v1:…`) for a key file store. The prompt goes to stderr,
so it also works inside `eval "$(envs export-shell prod)"`.

In scripts and CI there is nobody to answer. Without a terminal, `envs` never prompts. You can also force this on a
terminal with the global `--noinput` option (before the command name). A missing key then fails at once with exit
code 4:

```console
$ envs --noinput -c json://envs ls prod
Error: store 'prod' is encrypted and no key or passphrase was given; pass it with -k <path> (or -k - for stdin)
```

With several stores the hint names the store: `pass it with -k staging=<path> (or -k staging=- for stdin)`.

In CI, put the key file in your CI system's secret files, or pipe it from a secret variable on stdin:

```sh
printf '%s\n' "$PROD_ENVS_KEY" | envs --noinput run base prod -k prod=- -- ./deploy.sh
```

## Write secrets safely

`envs set NAME=value` is refused for encrypted stores, because the value would end up in your shell history:

```console
$ envs set -s prod A=1
Error: store 'prod' is encrypted: values on the command line end up in the shell history; give one name and pipe its value on stdin (envs set -s prod NAME < FILE) or type it at the hidden prompt (envs set -s prod NAME)
```

Give only the name, and either pipe the value in or type it at the hidden prompt:

```console
$ printf 'hunter2\n' | envs set -s prod DB_PASSWORD -k prod.key
set DB_PASSWORD in store 'prod'
$ envs set -s prod API_TOKEN -k prod.key           # on a terminal: asks twice, hidden
```

To add many secrets at once, use `envs import`. The safest way avoids a plaintext file: pipe the dotenv text in,
because `import` reads stdin when you leave out `-f` (or pass `-f -`):

```console
$ printf 'S1=a\nS2=b\n' | envs import -s prod -k prod.key
imported 2 variables into store 'prod'
```

If you do use a file (`envs import -s prod -k prod.key -f secrets.env`), create it with mode `0600` outside the
repository, never commit it, and delete it afterwards. Piping the data cannot be combined with `-k -`, because stdin
can be read only once:

```text
Error: stdin can be used only once per command: it is already used for the import input, so it cannot be used for -k -
```

## Encrypt, rotate, copy and decrypt

### Encrypt a plain store: `envs encrypt`

```console
$ envs create-store dev
created store 'dev'
$ envs set -s dev API_URL=https://dev.example.com
set API_URL in store 'dev'
$ envs encrypt -s dev --generate-key dev.key
encrypted store 'dev' (keyfile)
$ envs create-store ci
created store 'ci'
$ envs set -s ci LOG_LEVEL=info
set LOG_LEVEL in store 'ci'
$ envs keygen shared.key
wrote key file 'shared.key'
$ envs encrypt -s ci --new-key shared.key
encrypted store 'ci' (keyfile)
$ envs encrypt -s dev --generate-key dev2.key
Error: store 'dev' is already encrypted: use 'envs rekey -s dev'
```

Choose the key with exactly one of `--new-key PATH` (an existing key file, `-` for stdin), `--generate-key PATH`
or `--passphrase`. `encrypt` takes no `-k` and ignores `[keys]`; add the `[keys]` entry after encrypting. There is
no way back in place; see [decrypt](#remove-encryption-cp-store---plain) below.

Encrypting a store does not wipe older plaintext copies: backups, exports, or old database pages may still contain
the values. If the secrets were exposed in plain form, rotate them at their source too.

### Rotate a key: `envs rekey`

`rekey` re-encrypts a store with a new secret. It needs the old key (`-k`, `[keys]` or the prompt) and one new
secret:

```console
$ envs rekey -s dev -k dev.key --generate-key dev-new.key
rekeyed store 'dev' (keyfile)
$ envs ls dev -k dev.key
Error: cannot decrypt store 'dev': wrong key or passphrase, or the stored data was modified
$ printf 'my long passphrase\n' > dev.pass && chmod 600 dev.pass
$ envs rekey -s dev -k dev-new.key --passphrase < dev.pass
rekeyed store 'dev' (passphrase)
$ envs rekey -s prod -k prod.key
Error: give the new secret: --new-key, --generate-key or --passphrase
```

- `rekey` can switch between key file and passphrase mode, as above: `dev` is now a passphrase store, unlocked
  with `-k dev.pass`.
- A passphrase always gets a new salt.
- The old key stops working immediately, as the `ls dev -k dev.key` line shows.
  Update `[keys]` and every place that holds the old key (CI secrets, password manager) right after rekeying.
- `rekey` on a plain store points you to `envs encrypt`.

### Copy or move an encrypted store: `cp-store`, `mv-store`

Both need the source store's key. By default the copy is encrypted with the **same** key:

```console
$ envs mv-store ci tools -k shared.key
moved store 'ci' to 'tools'
$ envs cp-store dev dev-copy -k dev.pass --generate-key copy.key
copied store 'dev' to 'dev-copy'
```

| Option | The new store is… |
|---|---|
| *(none)* | encrypted with the same key or passphrase |
| `--new-key PATH` | encrypted with an existing key file (`-` for stdin) |
| `--generate-key PATH` | encrypted with a new key file |
| `--passphrase` | encrypted with a new passphrase |
| `--plain` | not encrypted |

Use only one of them. `--to URL` copies or moves into another backend, for example
`envs cp-store prod prod --to sqlite:////srv/backup/envs.db -k prod.key`.

### Remove encryption: `cp-store --plain`

There is no `decrypt` command. An encrypted store never turns into a plain store in place; you make a plain copy on
purpose:

```console
$ envs cp-store dev dev-decrypted -k dev.pass --plain
copied store 'dev' to 'dev-decrypted'
$ envs ls-store
name           encryption
base           plain
customer-a     encrypted (passphrase)
dev            encrypted (passphrase)
dev-copy       encrypted (keyfile)
dev-decrypted  plain
prod           encrypted (keyfile)
staging        encrypted (keyfile)
tools          encrypted (keyfile)
```

Delete the encrypted original afterwards with `envs rm-store dev -y` if you no longer need it.

## Which commands need a key

| Command | Key needed |
|---|---|
| `ls-store`, `rm-store`, `keygen`, `migrate` | no |
| `create-store -e` | a new one |
| `ls`, `get`, `export`, `export-shell`, `run` | yes, for each encrypted store you load |
| `set`, `rm`, `import` | yes |
| `cp-store`, `mv-store` | the source store's key (and optionally a new one) |
| `encrypt` | a new one (`--new-key`, `--generate-key` or `--passphrase`; no `-k`, no `[keys]`) |
| `tui` | yes, to open an encrypted store: from `[keys]` or the Unlock dialog (no `-k`) |
| `rekey` | the old one and a new one |

Note that `ls` needs the key even without `-v`: the variable names are encrypted too.

## Key errors and exit codes

| Situation | Message | Exit code |
|---|---|---|
| no key given, no prompt possible | `store 'prod' is encrypted and no key or passphrase was given: …` | 4 |
| wrong key or passphrase, or tampered data | `cannot decrypt store 'dev': wrong key or passphrase, or the stored data was modified` | 4 |
| key file for a passphrase store | `store 'dev' uses a passphrase, but a key file was given` | 4 |
| passphrase file for a key file store | `not a valid key file: expected one line 'envstore-key-v1:<base64url of 32 bytes>'; create one with envs keygen` | 4 |
| key file missing or unreadable | `cannot read key file 'missing.key': No such file or directory` | 4 |
| more than one key option for a new store | `use only one of -k, --generate-key, --passphrase` | 1 |
| empty key or passphrase on stdin | `the key or passphrase on stdin is empty` | 4 |
| `-k` for a plain store | `store 'base' is not encrypted; it takes no key or passphrase` | 1 |
| bare `-k PATH` with several stores | `-k <path> without a store name works with exactly one store; …` | 1 |
| `-k` names a store that is not loaded | `-k names store 'x', which is not in the store list` | 1 |

All messages start with `Error:` and go to stderr.

## If you lose the key

> [!WARNING]
> **There is no recovery.** If you lose the key file or forget the passphrase, the encrypted store cannot be read
> by anyone, including you and the maintainers. There is no backdoor, no reset and no master key.

To stay safe:

- Keep a copy of every key file or passphrase in a password manager or another safe place **separate from the
  stores**. `envs keygen -` prints a key you can paste straight into one.
- Before you rekey, make sure the new key is saved. The old key stops working the moment `rekey` succeeds.
- Do not pipe a freshly printed key straight into a store (`envs keygen - | envs create-store x -e -k -`): the key
  is used and then gone. Save it first, or use `--generate-key PATH`.
- If you still have the key but want to stop depending on it, make a plain copy with `cp-store --plain` or re-encrypt
  with `rekey`.

## See also

- [Configuration](configuration.md): connection strings, the project file and its trust check.
- [CLI reference](cli.md): every command, option and exit code.
- [Python library](python.md): `KeyMaterial`, `Passphrase`, `Path` keys and `generate_key_file()` from Python.
