"""Shell completion.

- `command`: `envs completion <shell>`, registered by `command.register`.
- `protocol`: the scripts and the answers to them; `EnvsGroup` hands requests to it.
- `candidates`: what parameter values complete to (stores, variables, paths).

This package module imports nothing, so `cli._typer` can import `protocol` without a cycle.
"""
