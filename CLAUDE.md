# Environment Store — agent instructions

- `main` is the base branch; branch off it for every change. The behaviour is documented in `docs/` and in
  the docstrings, user-visible changes in `CHANGELOG.md`.
- Read the [developer guide](docs/development/README.md) before changing code: it maps the layers, the test
  helpers and the checklists for adding an adapter, a CLI command or a TUI screen.
- **`CONTRIBUTING.md` is binding**: test-driven development, type hints everywhere, ty with `--error-on-warning`,
  ruff, bandit, 100 % line + branch coverage. Read it before writing code.
- Run the full definition of done (CONTRIBUTING.md §1) before reporting work as finished.
