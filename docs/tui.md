# Terminal UI

`envs tui` opens a full-screen terminal interface for your stores. You can browse the stores, create and remove
stores, export stores to a file, unlock an encrypted store, look at its variables with the values hidden, and add,
edit or delete variables. Every path input completes existing files and directories as you type. Everything else
(copying and renaming stores, import, `export-shell`, `encrypt`, `rekey`, `keygen`) stays in the
[command line](cli.md).

- [Install the tui extra](#install-the-tui-extra)
- [Start the TUI](#start-the-tui)
- [The screens at a glance](#the-screens-at-a-glance)
- [Key bindings](#key-bindings)
- [How do I…](#how-do-i)
- [Encrypted stores](#encrypted-stores)
- [Errors and changes made elsewhere](#errors-and-changes-made-elsewhere)
- [Limitations](#limitations)
- [Starting the TUI from Python](#starting-the-tui-from-python)

## Install the tui extra

The TUI is built on [Textual](https://textual.textualize.io/) and ships as an optional extra. The `envs` command
itself comes from the `cli` extra, so install both:

```sh
uv tool install 'environment-store[cli,tui]'
# or everything, including PostgreSQL support:
uv tool install 'environment-store[all]'
# with pip, in a virtual environment:
pip install 'environment-store[cli,tui]'
```

2.0 is not on PyPI yet; until it is, append the repository URL:
`uv tool install 'environment-store[cli,tui] @ git+https://github.com/mkaufhol/environment-store@feature/v2'`.

Without Textual, `envs tui` stops with exit code 1 and tells you what to install:

```
Error: this feature needs the optional 'tui' dependencies: uv add 'environment-store[tui]' (or pip install 'environment-store[tui]'); for the CLI tool: uv tool install 'environment-store[cli,tui]'
```

For the `envs` tool, the last command reinstalls it with `tui` added; list any other extras it already has, too. See [Installation](installation.md#optional-extras) for every extra.

## Start the TUI

```sh
envs -c json://envs tui
```

`envs tui` has no options of its own. It uses the same global settings as every other command, and they go
**before** `tui`:

| Setting | Where it comes from |
|---|---|
| Connection | `-c/--connection`, else `ENV_STORE_CONNECTION`, else `connection` in `.envstore.toml` |
| Keys for encrypted stores | `ENV_STORE_KEY_<STORE>`, else the `[keys]` table in `.envstore.toml`, else the Unlock dialog |
| Project file | `.envstore.toml` in the current directory or a parent; `--no-project` ignores it |

So in a project with an `.envstore.toml` that sets `connection`, a plain `envs tui` is enough. The project file's
`stores` list plays no role in the TUI: it always shows every store in the backend. `ordered_overwrite` only sets the
default of **First wins** in the export dialog (`ordered_overwrite = false` checks it). See
[Configuration](configuration.md) for the project file.

`envs tui` refuses to start when it cannot be interactive (exit code 1):

```console
$ envs -c json://envs tui < /dev/null
Error: envs tui needs a terminal: stdin and stdout must not be redirected
$ envs -c json://envs --noinput tui
Error: envs tui is interactive and cannot run with --noinput
```

When you quit normally the exit code is 0. If the TUI crashes, it prints a traceback (without the values of local
variables, so no secrets end up on screen) and exits with a non-zero code.

## The screens at a glance

The TUI has two full screens and several dialogs: create store, remove store, the three export steps, edit and add,
unlock, and confirm. Every screen has the title bar at the top and a footer at the bottom that lists the keys you can
press right now, including `⏎` (Enter) where it opens, edits, creates, removes, exports or unlocks. The dialogs show
their own keys in their footer.

### Stores

The first screen lists every store in the backend, sorted by name, with its encryption:

```
 ⭘                              Environment Store
 Store       Encryption
 customer-a  encrypted (passphrase)
 dev         plain
 prod        encrypted (keyfile)

 ⏎ Open  a Add  d Remove  x Export  r Reload  q Quit
```

The Encryption column shows `plain`, `encrypted (keyfile)` or `encrypted (passphrase)`. Listing the stores needs no
key, so you always see every store, encrypted or not.

If the backend holds no stores, the screen says so instead of showing an empty table. Press `a` to create one (see
[Create store](#create-store)):

```
 ⭘                              Environment Store
 Store  Encryption
No stores yet. Press a to create one

 ⏎ Open  a Add  d Remove  x Export  r Reload  q Quit
```

An empty list with stores you expected usually means a typo in the connection; `envs ls-store` shows the location
it looked at.

### Create store

`a` on the stores screen opens a dialog with the store name and its encryption, with every option of
`envs create-store`:

```
  Create a store
  ┌──────────────────────────────────────────┐
  │ Store name, e.g. base_conf               │
  └──────────────────────────────────────────┘
  Encryption
  ◉ None
  ○ New key file (generated)
  ○ Existing key file
  ○ Passphrase
   Create (ctrl+s)      Cancel (esc)

 ⏎ Create  ^s Create  esc Cancel
```

The name is checked as you type: an invalid name or the name of a listed store shows the problem below the field.
Choosing an encryption (`↑` / `↓`, then `Enter` or `Space`) shows its fields. With **New key file (generated)** the
key file path appears below the choice, and the footer adds `tab Complete path` while that field has the focus:

```
  Create a store
  ┌──────────────────────────────────────────┐
  │ prod                                     │
  └──────────────────────────────────────────┘
  Encryption
  ○ None
  ◉ New key file (generated)
  ○ Existing key file
  ○ Passphrase
  ┌──────────────────────────────────────────┐
  │ ./prod.key                               │
  └──────────────────────────────────────────┘
   Create (ctrl+s)      Cancel (esc)

 ⏎ Create  tab Complete path  ^s Create  esc Cancel
```

| Encryption | Like | Fields |
|---|---|---|
| None | `envs create-store NAME` | none |
| New key file (generated) | `--generate-key PATH` | where to write the new key file; it starts as `./NAME.key` and follows the name until you type a path of your own. An existing file is never overwritten, and the file gets mode `0600`. |
| Existing key file | `-k PATH` | the key file (from `envs keygen`) |
| Passphrase | `--passphrase` | the passphrase, typed twice; both fields are hidden |

The store is created before the dialog closes, so a problem (a key file that is not a key, passphrases that do not
match) keeps the dialog open with what you typed. If the store cannot be created, a newly generated key file is
removed again, unless the store may already use it; then the error says that the file was kept.

After a new passphrase or a generated key file, a yellow notification titled **Keep your key** reminds you that envs
does not save it, for example:

```
the new key was written to './prod.key'; envs does not save it anywhere else: keep it, or store 'prod' cannot be read again
```

### Remove store

`d` on the stores screen opens a dialog for the selected store. It says that the store and all its variables are
deleted and that this cannot be undone, and **Remove** works only once you have typed the store's name exactly:

```
  Remove store 'dev'? The store and all its variables are deleted. This cannot be undone.
  Type dev to confirm:
  ┌──────────────────────────────────────────┐
  │ dev                                      │
  └──────────────────────────────────────────┘
   Remove      Cancel (esc)

 ⏎ Remove  esc Cancel
```

If the typed name does not match, nothing is removed, the dialog stays open and says
`type the store name 'dev' exactly to remove it`. Like `envs rm-store`, removing needs no key, also for an
encrypted store.

### Export

`x` on the stores screen exports stores to a file, like `envs export`, in three steps:

1. **Choose the stores in load order.** `Space` (or `Enter`) chooses the store under the cursor; each chosen store
   shows its position, and the order you choose them in is the load order. Unchoosing a store renumbers the rest.
   `Ctrl+S` goes on.

   ```
     Export, step 1 of 3: choose the stores in load order (later stores win unless first wins is chosen)
      2  app   (plain)
      1  base  (plain)
         prod  (encrypted (keyfile))
      Next (ctrl+s)      Cancel (esc)

    space Choose  ^s Next  esc Cancel
   ```

2. **Choose the options**: the format (dotenv, JSON, TOML), **Nested** (`--nested`: one namespace per store instead
   of merging) and **First wins** (`--first-wins`). First wins starts checked when the project file sets
   `ordered_overwrite = false`. `Ctrl+S` goes on.
3. **Enter the output path.** The path input completes paths (see [Path completion](#path-completion)), and a typed
   extension (`.env`, `.json`, `.toml`) preselects the format, like `-t` on the command line; you can still change
   it. `Enter` or `Ctrl+S` exports.

   ```
     Export, step 3 of 3: the output file (mode 0600)
     ┌──────────────────────────────────────────┐
     │ config.json                              │
     └──────────────────────────────────────────┘
     Format (follows the file extension)
     ○ dotenv
     ◉ JSON
     ○ TOML
      Export (ctrl+s)      Cancel (esc)

    ⏎ Export  tab Complete path  ^s Export  esc Cancel
   ```

If the file exists, a confirmation asks `File 'config.json' exists already. Replace it?` (like `--force`). The keys of
encrypted stores come from the usual sources (see [Encrypted stores](#encrypted-stores)); for a store without one
the Unlock dialog opens. The file is written with mode `0600`, and a notification says `exported to 'config.json'`.
`Esc` in any step ends the export without writing anything.

### Variables

Opening a store shows its variables, sorted by name. The title bar names the store, and every value is hidden behind
the same eight dots, so you cannot guess a value from its length:

```
 ⭘                       Environment Store — store dev
 Variable  Value
 DB_HOST   ••••••••
 DEBUG     ••••••••
 GREETING  ••••••••

 ⏎ Edit  v Show / hide values  a Add  e Edit  d Delete  r Reload  esc Back  q Quit
```

Press `v` to show the values. A value that does not fit on one line (a newline, a tab, a carriage return) is shown as
a JSON string, for example `"line1\nline2"`. Values start hidden every time you open a store.

### Edit and Add

A dialog with a one-line name field and a multi-line value editor. When you edit, the name is fixed and the cursor
starts in the value; when you add, you type the name first.

```
  Edit 'DEBUG' in store 'dev'
  ┌──────────────────────────────────────────┐
  │ DEBUG                                    │
  └──────────────────────────────────────────┘
  ┌──────────────────────────────────────────┐
  │ true                                     │
  │                                          │
  └──────────────────────────────────────────┘
   Save (ctrl+s)      Cancel (esc)

 ^s Save  esc Cancel
```

### Unlock

Appears when you open an encrypted store and no key from the project file fits (see
[Encrypted stores](#encrypted-stores)):

```
  Unlock store 'prod', encrypted (keyfile)
  ┌──────────────────────────────────────────────┐
  │ Key or passphrase file, e.g. ~/.keys/a.key   │
  └──────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────┐
  │ or the passphrase                            │
  └──────────────────────────────────────────────┘
       Unlock         Cancel (esc)

 ⏎ Unlock  tab Complete path  esc Cancel
```

The key file field completes paths (see [Path completion](#path-completion)).

### Confirm

A yes/no question, for example `Delete variable 'DB_HOST' from store 'dev'?`. The **No** button has the focus, so a
stray Enter never confirms. Its footer reads `y Yes  n No  esc Cancel`; `Esc` answers no.

## Key bindings

### Stores screen

| Key | Action |
|---|---|
| `↑` / `↓`, `Page Up` / `Page Down`, `Home` / `End` | Move through the list |
| `Enter` | Open the selected store |
| `a` | Create a store |
| `d` | Remove the selected store (asks for its name) |
| `x` | Export stores to a file |
| `r` | Reload the list of stores |
| `q` | Quit |

### Variables screen

| Key | Action |
|---|---|
| `↑` / `↓`, `Page Up` / `Page Down`, `Home` / `End` | Move through the list |
| `v` | Show or hide the values |
| `a` | Add a variable |
| `e` or `Enter` | Edit the selected variable |
| `d` | Delete the selected variable (asks first) |
| `r` | Read the store again |
| `Esc` | Back to the stores (the key is forgotten) |
| `q` | Quit the TUI |

### Edit / Add dialog

| Key | Action |
|---|---|
| `Ctrl+S` | Save |
| `Esc` | Cancel, nothing is written |
| `Enter` in the name field | Move to the value editor |
| `Enter` in the value editor | A new line in the value |
| `Tab` / `Shift+Tab` | Move between fields and buttons |

### Unlock dialog

| Key | Action |
|---|---|
| `Enter` in either field | Unlock |
| `Tab` in the key file field | Accept the shown path suggestion; without one, move on |
| `Tab` / `Shift+Tab` | Move between the fields and buttons |
| `Esc` | Cancel and go back to the stores |

### Create store dialog

| Key | Action |
|---|---|
| `Enter` in any field, `Ctrl+S` | Create the store |
| `↑` / `↓` in the encryption choice, then `Enter` or `Space` | Choose the encryption |
| `Tab` in a key file path field | Accept the shown path suggestion; without one, move on |
| `Tab` / `Shift+Tab` | Move between fields and buttons |
| `Esc` | Cancel, nothing is created |

### Remove store dialog

| Key | Action |
|---|---|
| `Enter` | Remove the store, if the typed name matches exactly |
| `Esc` | Cancel, nothing is removed |

### Export dialogs

| Key | Action |
|---|---|
| `Space` or `Enter` in the store list | Choose or unchoose the store under the cursor (step 1) |
| `Ctrl+S` | Next step; in step 3, export |
| `Enter` in the path field | Export (step 3) |
| `Tab` in the path field | Accept the shown path suggestion; without one, move on |
| `Tab` / `Shift+Tab` | Move between fields and buttons |
| `Esc` | Cancel the export, nothing is written |

### Footers

The footer changes with the screen and with the field that has the focus. These are all of them:

| Where | Footer |
|---|---|
| Stores screen | `⏎ Open  a Add  d Remove  x Export  r Reload  q Quit` |
| Variables screen | `⏎ Edit  v Show / hide values  a Add  e Edit  d Delete  r Reload  esc Back  q Quit` |
| Create store: name or passphrase field | `⏎ Create  ^s Create  esc Cancel` |
| Create store: encryption choice | `^s Create  esc Cancel` |
| Create store: a key file path field | `⏎ Create  tab Complete path  ^s Create  esc Cancel` |
| Remove store | `⏎ Remove  esc Cancel` |
| Export, step 1 (stores) | `space Choose  ^s Next  esc Cancel` |
| Export, step 2 (options) | `^s Next  esc Cancel` |
| Export, step 3 (path) | `⏎ Export  tab Complete path  ^s Export  esc Cancel` |
| Unlock: key file field | `⏎ Unlock  tab Complete path  esc Cancel` |
| Unlock: passphrase field | `⏎ Unlock  esc Cancel` |
| Edit / Add | `^s Save  esc Cancel` |
| Confirm | `y Yes  n No  esc Cancel` |

### Path completion

Every path input (the export path, the key file fields of the create store and unlock dialogs) suggests the first
existing file or directory that completes what you typed, shown dimmed after the cursor:

| Key | Action |
|---|---|
| `Tab` | Accept the suggestion, when one is shown and the cursor is at the end; otherwise move to the next field |
| `→` | Accept the suggestion |

A leading `~` is expanded for the lookup and kept in the text (as with `-k` on the command line, `./~/a`
names a directory called `~`), directories end in `/`, and matching is case-sensitive.
Hidden files and directories are suggested only once you type a `.`. A directory that cannot be read suggests
nothing.

### Confirm dialog

| Key | Action |
|---|---|
| `y` | Yes |
| `n` | No |
| `Esc` | Cancel (the same as No) |

### Available everywhere

These come from Textual itself, not from Environment Store:

| Key | Action |
|---|---|
| `Ctrl+Q` | Quit from any screen |
| `Ctrl+C` | Does **not** quit. It only shows a hint (or copies the selected text in an input field). Quit with `q` on the stores or variables screen, or `Ctrl+Q` anywhere. |

Textual's command palette (`Ctrl+P`) is turned off: its screenshot command would save the whole screen, including
revealed values, to a plain file. Still, don't reveal values with `v` while you share your screen.

You can also click rows and buttons with the mouse.

## How do I…

### …look at a value?

Select the store and press `Enter`, then press `v`. Press `v` again to hide the values.

### …add a variable?

On the variables screen press `a`, type the name, press `Enter` to move to the value, type the value and press
`Ctrl+S`. The name must be a valid variable name: letters, digits and `_`, not starting with a digit. A bad name or
a name that already exists keeps the dialog open with what you typed and shows the problem, for example:

```
variable 'DEBUG' exists already in store 'dev': edit it
```

### …change a value?

Select the variable and press `e` or `Enter`, change the value, press `Ctrl+S`. If you save without changing
anything, the dialog closes and nothing is written. The value may be empty and may span several lines; whatever is
in the editor is stored exactly, with no trailing newline added or removed.

### …delete a variable?

Select it, press `d`, then `y`. `n` or `Esc` keeps it.

### …create a store?

On the stores screen press `a`, type the name, choose the encryption and fill in its fields, then press `Enter` or
`Ctrl+S`. See [Create store](#create-store).

### …remove a store?

Select it, press `d`, type its name exactly and press `Enter`. `Esc` keeps it. See [Remove store](#remove-store).

### …export stores to a file?

On the stores screen press `x`, choose the stores in load order with `Space`, press `Ctrl+S`, choose the options,
press `Ctrl+S`, type the path and press `Enter`. See [Export](#export).

### …rename or copy a store?

Not in the TUI. Use [`envs mv-store` and `envs cp-store`](cli.md), then press `r` on the stores screen to see the
change.

## Encrypted stores

When you open an encrypted store, the TUI looks for its key in this order:

1. **The variable `ENV_STORE_KEY_<STORE>`** (`ENV_STORE_KEY_CUSTOMER_A` for `customer-a`). When it is set, it alone
   is tried; if it does not work, the TUI shows the error, naming the variable but never its value, and opens the
   Unlock dialog. See [Deployment](deployment.md).
2. **The `[keys]` table of `.envstore.toml`.** If the project file names a key or passphrase file for the store, the
   store opens without asking:

   ```toml
   # .envstore.toml
   connection = "json://envs"

   [keys]
   prod = "keys/prod.key"          # relative to the project file's directory
   customer-a = "~/.keys/customer-a.pass"
   ```

3. **The Unlock dialog.** If there is no `[keys]` entry, or the entry does not work (missing file, wrong key), the
   TUI shows the error, naming the file it tried, and opens the Unlock dialog:

   ```
   unlocking with the key file '/home/me/project/keys/prod.key' from the project file failed: cannot read key or passphrase file '/home/me/project/keys/prod.key': No such file or directory
   ```

In the Unlock dialog fill in **exactly one** of the two fields:

- **Key or passphrase file**: the path to a key file (from `envs keygen`) for a `keyfile` store, or to a file that
  holds the passphrase for a `passphrase` store. `~` is expanded. One trailing newline in a passphrase file is
  ignored.
- **or the passphrase**: type the passphrase itself. The field is hidden. For a `keyfile` store you can paste the
  key text here instead (the `envstore-key-v1:...` line, for example from a password manager after `envs keygen -`),
  so the key never has to be on disk. If you type a passphrase into this field for a `keyfile` store, you get
  `unlocking with the typed passphrase failed: not a valid key file: expected one line 'envstore-key-v1:<base64url of 32 bytes>'; create one with envs keygen`.

Then press `Enter` or click **Unlock**. The store is decrypted before the dialog closes:

- With the wrong key the dialog stays open, shows the error with the input it came from, for example
  `unlocking with the key file 'old.key' failed: cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified`,
  and clears the passphrase field.
- With both fields empty, or both filled, it asks you to `enter either a key or passphrase file, or the passphrase`.
- A key file for a passphrase store, or a passphrase file for a keyfile store, is refused with the same messages as
  in the CLI (see [Encryption](encryption.md)).

Unlocking a passphrase store takes a moment: the passphrase goes through Argon2id with 64 MiB of memory on
purpose.

**The key is kept only while the store is open.** When you press `Esc` to go back to the stores, the key is
forgotten; opening the store again uses `[keys]` or asks again. The TUI never saves or caches keys.

Values you add or edit in an encrypted store are encrypted with the key you unlocked it with. Typing a secret into
the TUI keeps it out of your shell history, just like `envs set -s prod NAME` with the hidden prompt.

## Errors and changes made elsewhere

Problems appear as a red notification titled **Error** in the corner of the screen. It shows the message the CLI
would print, without remedies that only make sense on the command line (such as `-o`), and never a value or a key. For example, a `[keys]` entry for a plaintext store:

```
[keys] in '/home/me/project/.envstore.toml' names a key for store 'dev', which is not encrypted: remove the entry
```

The TUI remembers which revision of a store it is showing. If someone else (another terminal, a CI job, a teammate on
the same database) changes the store while you have it open, your next save or delete writes **nothing** and you get
a question:

```
store 'prod' was changed elsewhere since it was read; nothing was written: reload it and try again. Reload store 'prod' now?
```

Press `y` to read the store again, then repeat your change. Nothing is ever overwritten silently.

## Limitations

- **Some commands are CLI-only.** `cp-store`, `mv-store`, `import`, `export-shell`, `encrypt`, `rekey` and `keygen`.
  The TUI creates, removes and exports stores (to a file only), and edits variables.
- **One store at a time.** The variables screen shows one store; it does not merge stores the way `envs ls base dev`
  does. Only the export merges stores. The TUI ignores `stores` in the project file; `ordered_overwrite` only sets
  the export dialog's default.
- **One variable per write.** Each save or delete is its own write. To change many variables in one write, use
  `envs import`, or, for a plaintext store only, `envs set` with several `KEY=VALUE` pairs. Encrypted stores refuse
  `KEY=VALUE` pairs: `envs set` takes one `KEY` with its value piped in or typed at the hidden prompt.
- **Some multi-line values cannot be edited.** A value with mixed line endings (for example `\r\n` and `\n` in one
  value) or other line separators would not survive the editor unchanged, so the TUI refuses to edit it:

  ```
  variable 'MIXED' has line breaks the editor cannot keep unchanged (mixed line endings or other line separators): change it with 'envs set'
  ```

  You can still view and delete such a variable. Change it with `envs set` or `envs import`.
- **Interactive only.** No `--noinput`, no redirected stdin or stdout. For scripts and CI use the [CLI](cli.md) or
  the [Python library](python.md).
- **Keys like the CLI.** The TUI takes a store's key from `ENV_STORE_KEY_<STORE>`, else from `[keys]`, else from
  what you type.

## Starting the TUI from Python

The `environment_store.tui` package exposes `run_tui` and the Textual app class `EnvironmentStoreApp`. Importing the
package without the `tui` extra raises `MissingExtraError`.

```python
from pathlib import Path

from environment_store import EnvironmentStore
from environment_store.tui import run_tui

with EnvironmentStore("json://envs") as store:
    run_tui(store, key_paths={"prod": Path("prod.key")})
```

| Parameter | Meaning |
|---|---|
| `store` | An open `EnvironmentStore`. You close it after the TUI ends. |
| `key_paths` | Required, keyword-only. Store name → key or passphrase file, used like `[keys]` before asking. Pass `{}` to always ask in the Unlock dialog. |
| `project_file` | Optional path of the project file, only used to name it in error messages. |
| `ordered_overwrite` | Optional, default `True` (last wins). `False` checks **First wins** in the export dialog by default. |

`run_tui` blocks until the user quits. After a crash it raises `SystemExit` with the app's non-zero return code.
