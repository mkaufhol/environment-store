# Terminal UI

`envs tui` opens a full-screen terminal interface for your stores. You can browse the stores, unlock an encrypted
one, look at its variables with the values hidden, and add, edit or delete variables. Everything else (creating,
copying and deleting stores, import and export, keys) stays in the [command line](cli.md).

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
pip install 'environment-store[cli,tui]'
# or everything, including PostgreSQL support:
pip install 'environment-store[all]'
```

Without Textual, `envs tui` stops with exit code 1 and tells you what to install:

```
Error: this feature needs the optional 'tui' dependencies: pip install 'environment-store[tui]'
```

See [Installation](installation.md) for `uv` and `pipx`.

## Start the TUI

```sh
envs -c json://envs tui
```

`envs tui` has no options of its own. It uses the same global settings as every other command, and they go
**before** `tui`:

| Setting | Where it comes from |
|---|---|
| Connection | `-c/--connection`, else `ENV_STORE_CONNECTION`, else `connection` in `.envstore.toml` |
| Keys for encrypted stores | the `[keys]` table in `.envstore.toml`, else the Unlock dialog |
| Project file | `.envstore.toml` in the current directory or a parent; `--no-project` ignores it |

So in a project with an `.envstore.toml` that sets `connection`, a plain `envs tui` is enough. The project file's
`stores` list and `ordered_overwrite` play no role in the TUI: it always shows every store in the backend, one at a
time. See [Configuration](configuration.md) for the project file.

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

The TUI has two full screens and three dialogs. Every screen has the title bar at the top and a footer at the bottom
that lists the keys you can press right now.

### Stores

The first screen lists every store in the backend, sorted by name, with its encryption:

```
 ⭘                              Environment Store
 Store       Encryption
 customer-a  encrypted (passphrase)
 dev         plain
 prod        encrypted (keyfile)

 r Reload  q Quit                                                  ▏^p palette
```

The Encryption column shows `plain`, `encrypted (keyfile)` or `encrypted (passphrase)`. Listing the stores needs no
key, so you always see every store, encrypted or not.

### Variables

Opening a store shows its variables, sorted by name. The title bar names the store, and every value is hidden behind
the same eight dots, so you cannot guess a value from its length:

```
 ⭘                       Environment Store — store dev
 Variable  Value
 DB_HOST   ••••••••
 DEBUG     ••••••••
 GREETING  ••••••••

 v Show / hide values  a Add  e Edit  d Delete  r Reload  esc Back  ▏^p palette
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
```

### Confirm

A yes/no question, for example `Delete variable 'DB_HOST' from store 'dev'?`. The **No** button has the focus, so a
stray Enter never confirms.

## Key bindings

### Stores screen

| Key | Action |
|---|---|
| `↑` / `↓`, `Page Up` / `Page Down`, `Home` / `End` | Move through the list |
| `Enter` | Open the selected store |
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
| `Tab` / `Shift+Tab` | Move between the fields and buttons |
| `Esc` | Cancel and go back to the stores |

### Confirm dialog

| Key | Action |
|---|---|
| `y` | Yes |
| `n` or `Esc` | No |

### Available everywhere

These come from Textual itself, not from Environment Store:

| Key | Action |
|---|---|
| `Ctrl+Q` | Quit from any screen |
| `Ctrl+P` | Open Textual's command palette (theme, keys help, screenshot, quit) |
| `Ctrl+C` | Does **not** quit. It only shows a hint (or copies the selected text in an input field). Quit with `q` on the store list or `Ctrl+Q` anywhere. |

> [!WARNING]
> The palette's **screenshot** command saves an SVG of the whole screen to your Downloads folder. If you revealed the
> values with `v`, every value on screen ends up in that plain file. Press `v` to hide the values before you take a
> screenshot, and don't reveal values while you share your screen.

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

### …create, rename or delete a store?

Not in the TUI. Use [`envs create-store`, `envs mv-store` and `envs rm-store`](cli.md), then press `r` on the stores
screen to see the change.

## Encrypted stores

When you open an encrypted store, the TUI looks for its key in this order:

1. **The `[keys]` table of `.envstore.toml`.** If the project file names a key or passphrase file for the store, the
   store opens without asking:

   ```toml
   # .envstore.toml
   connection = "json://envs"

   [keys]
   prod = "keys/prod.key"          # relative to the project file's directory
   customer-a = "~/.keys/customer-a.pass"
   ```

2. **The Unlock dialog.** If there is no `[keys]` entry, or the entry does not work (missing file, wrong key), the
   TUI shows the error and opens the Unlock dialog.

In the Unlock dialog fill in **exactly one** of the two fields:

- **Key or passphrase file**: the path to a key file (from `envs keygen`) for a `keyfile` store, or to a file that
  holds the passphrase for a `passphrase` store. `~` is expanded. One trailing newline in a passphrase file is
  ignored.
- **or the passphrase**: type the passphrase itself. The field is hidden. For a `keyfile` store you can paste the
  key text here instead (the `envstore-key-v1:...` line, for example from a password manager after `envs keygen -`),
  so the key never has to be on disk. If you type a passphrase into this field for a `keyfile` store, you get
  `not a valid key file: expected one line 'envstore-key-v1:<base64url of 32 bytes>' (create one with keygen)`.

Then press `Enter` or click **Unlock**. The store is decrypted before the dialog closes:

- With the wrong key the dialog stays open, shows
  `cannot decrypt store 'prod': wrong key or passphrase, or the stored data was modified`, and clears the passphrase
  field.
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

Problems appear as a red notification titled **Error** in the corner of the screen. It shows the same message the
CLI would print, never a value or a key. For example, a `[keys]` entry for a plaintext store:

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

- **Variables only.** Store lifecycle (`create-store`, `rm-store`, `cp-store`, `mv-store`), `import`, `export`,
  `encrypt`, `rekey` and `keygen` are CLI-only.
- **One store at a time.** The TUI does not merge stores the way `envs ls base dev` does, and it ignores `stores`
  and `ordered_overwrite` in the project file.
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
- **No key in an environment variable.** Like the rest of the tool, the TUI reads keys only from `[keys]` or what you
  type.

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

`run_tui` blocks until the user quits. After a crash it raises `SystemExit` with the app's non-zero return code.
