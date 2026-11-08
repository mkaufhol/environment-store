# Keeping the documentation in sync

The user documentation is part of the product, and most of it is checked by tests in `tests/docs/`.
A CLI change that skips the docs fails the suite. This page lists what each document covers, what
the tests check, and which documents a typical change touches.

## The documents

| Document | Audience | Maintained |
|---|---|---|
| `README.md` | PyPI and GitHub visitors | by hand; **absolute links only**, because PyPI renders it without the repository |
| `docs/README.md` | users: the index of the guides | by hand; must link every guide in `docs/` |
| `docs/*.md` | users: quickstart, installation, CLI, Python, configuration, encryption, deployment, TUI | by hand |
| `docs/development/` | contributors: this guide | by hand; the index must link every page |
| `docs/man/share/man/man1/envs.1` | `man envs`, installed with the wheel | by hand, in roff; nothing generates it |
| `docs/tldr/envs.md` | a page in the tldr-pages format | by hand |
| `.claude/skills/environment-store-cli/` | coding agents that *use* the `envs` CLI | by hand |
| `CHANGELOG.md` | users upgrading | by hand, Keep a Changelog format |
| Docstrings | library users and maintainers | Google style; CLI callback docstrings are the `--help` texts |

## What the tests check

| Test module | Checks |
|---|---|
| `tests/docs/test_documentation.py` | Every CLI command is named in `docs/cli.md` and in the skill's `SKILL.md`. Relative links and heading anchors resolve. `docs/README.md` links every guide. `docs/python.md` names every public library name. Shown versions match `pyproject.toml`. Quoted `MissingExtraError` messages match the real message exactly. `## [Unreleased]` is the first changelog section, the version has an entry that names the minimum Python, and the changelog names every `ENV_STORE_*` variable. Documented minimum Python versions match `requires-python`. `docs/README.md`, `CONTRIBUTING.md` and `CLAUDE.md` link this guide. For this guide: every page is linked, every repository path it names exists, the layer table matches the import rules, and every registered scheme is named. |
| `tests/docs/test_reference_pages.py` | The man page documents every command, every option of every command, the global options, the exit codes, the environment variables and the project file, and nothing that doesn't exist. If `mandoc` is installed (it isn't in CI), the page must render without warnings. The tldr page has one to eight well-formed examples that use only real commands and options. |
| `tests/docs/test_completion_docs.py` | The shell completion setup appears in each guide that explains it, and the documented scripts really work when saved as files. The TUI section of `docs/cli.md` lists the store keys, and `docs/README.md` links the completion sections and the TUI flows, so renaming those headings fails here too. |
| `tests/docs/test_tui_footers.py` | Drives every TUI screen and dialog headless and compares each footer with the footers drawn in `docs/tui.md`, in both directions. |

**What the tests don't check:**

- Code blocks in the docs are not executed.
- External links are not fetched.
- The lists of supported schemes and extras in the user guides are not checked.

So run the commands you document, and copy their output from a real run.

**Rules that are easy to miss:**

- **How a command is mentioned.** A command name counts only in a heading or an inline code span.
  Inside a fenced code block it doesn't count, so the skill's cheat sheet alone doesn't satisfy
  the check.
- **Versions.** `environment-store` followed by a number, anywhere in a document (code blocks
  included), and any code span that holds only a version, must show the current package version.
  Write dependency versions in prose, not as a code span on their own.
- **Branches.** Links into the repository point to `main`, never to a feature branch.
- **Library error quotes.** `docs/python.md` must not show CLI wording in quoted library errors:
  no flags, and no `envs` or `keygen`. The library's hints name parameters.

## What a change touches

### A CLI command or option

- `docs/cli.md`:
  - a section ``#### `envs <command>` — <summary>`` under the commands, with its synopsis and an
    options table;
  - any recipe that changes.
- `docs/man/share/man/man1/envs.1`:
  - a `.SS <command>` subsection with a `.B envs <command>` synopsis and one `.TP` entry per
    option;
  - the option names in the synopsis and the `.TP` heads are compared with the real options in
    both directions;
  - if `mandoc` is installed, run `mandoc -T lint -W warning` on the page.
- **A global option** (an option of `envs` itself): its `.TP` entry in the man page's
  `GLOBAL OPTIONS` section, which is compared with the real global options in both directions, and
  the global options table in `docs/cli.md`.
- `.claude/skills/environment-store-cli/SKILL.md`: the command in a heading or code span, and the
  cheat sheet line.
- `.claude/skills/environment-store-cli/reference.md`: the options, if agents need them.
- `docs/tldr/envs.md`: add an example only if the command is among the most common tasks. The page
  already holds the maximum of eight, so a new example replaces one. A renamed or removed option
  must be updated in every example that uses it.
- `docs/README.md`: a row in "How do I…" for a new task.

### A TUI change

- `docs/tui.md`: the screen's description and its exact footer in a fenced block.
- `docs/cli.md`: the keys table in the TUI section.
- The man page `tui` section: its `.TP` list holds the stores-screen keys plus `Tab` for path
  inputs. `test_man_page_tui_section_lists_the_new_keys` pins that exact list, so update the test in
  the same change.

### A library change

- `docs/python.md`: every public name, with an example for new behaviour.
- The docstrings of public functions and classes: they are the API reference.
- If you change an error message that a document quotes, update the quotes.

### A configuration change

- `docs/configuration.md`: precedence, the project file and environment variables.
- The man page's `ENVIRONMENT` and `FILES` sections.
- `docs/deployment.md`, if it changes how deployed apps get their keys.

### A new guide page

- **A user guide** goes into `docs/` and gets a row in the table in `docs/README.md`.
- **A developer guide page** goes into `docs/development/` and gets a row in the table in
  [the guide's index](README.md#the-guide).

### Every user-visible change

- **Changelog.** An entry under `## [Unreleased]` in `CHANGELOG.md`.
- **Agent skill.** If the change affects how agents should call the CLI, update the skill's rules
  in `SKILL.md`, not only its reference.

## Writing style

- **Short sentences, concrete examples.** Show the command, then its real output.
- **Name the exact thing:** the flag, the file, the variable, the exit code.
- **Explain why** a rule exists when users could otherwise work around it, for example why a store
  is bound to its name.
- **In docstrings and comments, explain the reason in place.** Never point at a document, issue or
  plan.
