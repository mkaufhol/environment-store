# Extending the CLI, the TUI and the library

Each checklist below names the files to touch and the test that fails when a step is missing.
Start every change with the failing test that describes the new behaviour; the checklists are the
rest of the work.

## Where new behaviour goes

Put a rule in the lowest layer that can own it, and let the frontends call it:

| The change is… | Put it in |
|---|---|
| a rule about names, values, records, merging | `core` |
| an operation on stores or variables (read, write, copy, re-seal) | `service.py`, exposed through `EnvironmentStore` in `library/store.py` |
| where a setting or key comes from (flags, environment, project file, prompt) | `config` |
| a file format for import or export | `formats` |
| how something is shown, asked or exited with | `cli` or `tui` |

A command that needs logic the library doesn't offer yet gets a library method first, with its own
tests in `tests/unit/library/`. The CLI and TUI then call that method. Both frontends behave the
same because they share it.

## Add a CLI command

1. **Tests.** Create `tests/cli/<area>/test_<command>.py`. Use the `cli` fixture for the main
   paths and `cli_json` for error cases (see [Testing](testing.md#cli-tests)). Cover:
   - every exit code the command can return;
   - `--json` output, if the command has it;
   - `--noinput` and `-y`, if it prompts or asks for confirmation;
   - that secrets never appear in the output.
2. **The callback.** Write it in the matching package under `src/environment_store/cli/`
   (`stores/`, `variables/`, `exporting/`, `encryption/`), or in a new module:

   ```python
   def rename_variable(
       ctx: typer.Context,
       old: Annotated[
           str, typer.Argument(help="The current name.", autocompletion=complete_variables)
       ],
       new: Annotated[str, typer.Argument(help="The new name.")],
       *,
       store: StoreOpt,
       key: WriteKeyOpt = None,
   ) -> None:
       """Rename a variable in one store."""
       secret = existing_secret(ctx, store, key)
       get_state(ctx).open_store(ctx).rename(store, old, new, key=secret)
       err(f"renamed {old} to {new} in store '{store}'")
   ```

   - **The library method first.** The sample assumes an `EnvironmentStore.rename` method, added
     first with its own tests (see [Where new behaviour goes](#where-new-behaviour-goes)).
   - **Docstring.** Typer prints the whole docstring as the `--help` text, and its first line is
     the summary in `envs --help`. Write it for users, without `Args:` or `Returns:` sections.
   - **Options.** Options are keyword-only, after `*`. Reuse the shared `Annotated` aliases in
     `src/environment_store/cli/options.py`; add a new alias there, and to its `__all__`, when two
     commands share an option.
   - **Stores.** Open stores with `get_state(ctx).open_store(ctx)`. They are closed automatically
     when the command ends, so never close them yourself.
   - **Reading commands** load through `load_for_reading` in `cli/loading.py`. **Keys** for existing
     stores come from `existing_secret` in `cli/secrets.py`. **Confirmations** use
     `require_confirmation` in `cli/confirm.py`.
   - **Output.** Data goes to stdout through `out` or `emit_json` in `cli/output.py`. Messages,
     including success messages, go to stderr through `err`. Never call `print` or `typer.echo`.
   - **Stdin.** Read it only through `CliState.claim_stdin` and `read_stdin`, so two options can't
     both consume it.
3. **Registration.** Register the command in its package's `register(app)` with an explicit name
   and a command class from `cli/_typer.py`:

   | Class | For |
   |---|---|
   | `EnvsCommand` | almost every command. It resolves the settings before the callback, so a broken project file fails the same way everywhere. |
   | `OfflineCommand` | commands that must work without a connection or project file, like `keygen` and `completion` |
   | `PassthroughCommand` | commands that pass everything after `--` on, like `run` |

   A new package gets its own `register` function, called from `build_app()` in
   `src/environment_store/cli/app.py`. `tests/cli/foundation/test_registration.py` fails for a
   command registered without one of these classes.
4. **Command tables.** Add the name to `_COMMANDS` in `tests/cli/test_command_table.py` and update
   the expected count there. Also add it to `_COMMANDS` in `tests/cli/completion/test_protocol.py`,
   whose completion tests compare the completed command names with that set.
5. **Help.** `tests/cli/foundation/test_help_shorthand.py` runs `-h` and `--help` for every command,
   without a connection and with a broken project file. It fails if the command does any work
   before its callback runs. If the exact wording of a help text matters, pin it in
   `tests/cli/foundation/test_help_texts.py`.
6. **Completion.** Give store and variable arguments `autocompletion=complete_stores` or
   `complete_variables`, and file paths `click_type=PathType()`, all from
   `cli/completion/candidates.py`. Test them in `tests/cli/completion/test_candidates.py`.
7. **Documentation.** The command must appear in `docs/cli.md`, the man page and the agent skill;
   tests check all three. See [Documentation](documentation.md#a-cli-command-or-option).
8. **Changelog.** Add an entry under `## [Unreleased]` in `CHANGELOG.md`.

**Adding an option** to an existing command follows the same steps without the registration. The man
page tests check every option in both directions: a new option must be named in its command's
section (document it in a `.TP` entry), and a removed option must disappear from the synopsis and
the `.TP` entries. A tldr example that uses a renamed option fails too.

### Rules the CLI tests enforce

- **Never import `click` or `typer._click` at runtime.** typer vendors click privately: import it
  only in `if TYPE_CHECKING:` blocks, for annotations, as `cli/_typer.py` and `cli/completion/` do.
  `tests/cli/foundation/test_typer_boundary.py` checks every module.
- **Usage errors exit with 1,** not click's 2.
- **An option named `store`** gets a hint on a missing `-s` automatically when the project file
  lists `stores` (`EnvsCommand.parse_args`).
- **No `rich` markup.** The app sets `rich_markup_mode=None`, so square brackets in help texts stay
  literal.

## Add a TUI screen or action

1. **Tests.** Write Pilot tests in `tests/tui/test_<screen>.py` with `run_app` from
   `tests/tui/pilot.py`, using the `store` and `other` fixtures for a second, concurrent user.
2. **Library calls.** Put every library call in a `StoreSession` method in
   `src/environment_store/tui/session.py`, with tests in `tests/tui/test_session.py` or
   `tests/tui/test_session_stores.py`. Screens never call `EnvironmentStore` themselves; pure
   helpers such as `parse_key_text` are the only library calls outside the session. Dialog results
   are plain values or frozen dataclasses. The choices dialogs pass to the session (new keys, export
   options) live in `src/environment_store/tui/choices.py`.
3. **The screen.** Add it to `src/environment_store/tui/screens/`:
   - Use `Screen[None]` for a full screen and `ModalScreen[Result]` for a dialog that returns a
     value with `self.dismiss(result)`.
   - Declare keys in `BINDINGS`; their labels become the footer.
   - Wrap dialog content in a `Vertical(classes="dialog")` and add a `Footer()`.
   - Create every `Label` and `Static` with `markup=False`, so a store or variable name can't
     inject markup.
4. **Wiring.** Add an `action_<name>` method and a `Binding` to the parent screen, and open the
   dialog with `self.app.push_screen(Dialog(...), callback)`. The callback catches
   `EnvironmentStoreError` and calls `notify_error` from `src/environment_store/tui/messages.py`.
   For a flow of several dialogs, follow `ExportFlow` in `src/environment_store/tui/exporting.py`.
5. **Hints.** If a library error needs a TUI-specific remedy, add it to `_TUI_HINTS` in
   `tui/messages.py`, with a test in `tests/tui/test_messages.py`.
6. **Footers.**
   - Update the expected footers in `tests/tui/test_keys.py`.
   - Extend `_visit` in `tests/docs/test_tui_footers.py` so it notes every footer of the new screen,
     including footers that change with the focus, and update the footer count in
     `test_the_scenario_reaches_every_screen_and_dialog`.
   - Draw the exact footer in `docs/tui.md`; the footer test compares both directions.
7. **Keys.** A new key on the stores screen also goes into the TUI keys table in `docs/cli.md` and
   the `tui` section of the man page. Update the tests for both:
   - `tests/docs/test_reference_pages.py::test_man_page_tui_section_lists_the_new_keys` pins the man
     page's key list exactly;
   - `tests/docs/test_completion_docs.py::test_the_cli_guides_tui_section_lists_the_store_keys` only
     checks the keys it lists, so add the new key to its parameters.
8. **Changelog.** Add an entry under `## [Unreleased]` in `CHANGELOG.md`.

The command palette stays disabled (`ENABLE_COMMAND_PALETTE = False`), because its screenshot
action could write variable values to disk.

## Add an error class

1. **Category.** Derive from the right category in `src/environment_store/core/errors.py`. The
   category decides the exit code; a class outside the four mapped categories exits with 1.
2. **Message.** Put what failed in `detail` and the library remedy in `hint`, naming library
   parameters only. `tests/docs/test_documentation.py::test_python_guide_quotes_no_cli_flags_in_library_errors`
   catches CLI flags in the Python guide's quoted errors.
3. **Exports.**
   - Add the class to `__all__` in `core/errors.py`.
   - Import and list it in `src/environment_store/core/__init__.py`.
     `tests/unit/core/test_core_package.py` checks that `core` re-exports every name of its modules.
   - Make it public: [Add a public name](#add-a-public-name-to-the-library). `_PUBLIC` in
     `tests/unit/test_package.py` already includes every name in `errors.__all__`.
4. **Exit code test.** Add it to `_EXPECTED` in `tests/cli/foundation/test_errors.py`, which maps
   every class to its exit code.
5. **Frontend remedies.** If the CLI or the TUI should show its own remedy, add it to `_CLI_HINTS`
   in `cli/errors.py` and to `_TUI_HINTS` in `tui/messages.py`.
6. **Changelog.** Add an entry under `## [Unreleased]` in `CHANGELOG.md`.

## Add a public name to the library

The public API is the set of names in `environment_store.__all__`, resolved lazily so that
`import environment_store` stays cheap. A new public name needs all of these:

- **`src/environment_store/__init__.py`:**
  - an entry in `_DEFINITIONS`, which says where the name lives;
  - the name in `__all__`;
  - an import in the `if TYPE_CHECKING:` block, for type checkers.
- **`tests/unit/test_package.py`:** the name and its defining module in `_PUBLIC`. Error classes are
  already covered there through `errors.__all__`.
- **`docs/python.md`:** the name, documented.
  `test_python_guide_names_every_public_name_of_the_library` fails until it appears.

Public signatures carry no `Any`. Their docstrings are user documentation.

## Add an environment variable or a project-file key

- **Precedence.** Settings follow option > environment variable > project file > default
  (`config/settings.py`). Keep that order, and treat an empty environment variable as unset.
- **The project file.** `config/project.py` rejects unknown keys, so add a new key to
  `_ALLOWED_KEYS` and validate its type there. A path in the project file is anchored to the
  file's directory.
- **The name.** Every `ENV_STORE_*` variable that `src/` reads must be named in `CHANGELOG.md`.
  `test_changelog_names_every_environment_variable_the_package_reads` greps for them.
- **Documentation:**
  - `docs/configuration.md`;
  - the `ENVIRONMENT` section of the man page, plus the variable in `_ENVIRONMENT` in
    `tests/docs/test_reference_pages.py`, which checks that the man page names it;
  - the agent skill, where it changes how agents call the CLI.

## Add an optional extra

- **The import.** Import the dependency only in the module that needs it, and raise
  `MissingExtraError("<extra>")` when it is missing. Never import it from a module that loads at
  `import environment_store`.
- **`pyproject.toml`.** Add the extra, add it to `all`, and add the dependency to the `testing`
  group; see [Tools](tooling.md#dependencies).
- **Documentation.** Document the extra in `docs/installation.md`, `docs/cli.md` and
  `docs/python.md`. Docs that quote the missing-extra message must quote it exactly
  (`test_quoted_missing_extra_messages_match_the_error`).
