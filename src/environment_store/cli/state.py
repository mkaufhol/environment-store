"""`CliState`: the per-invocation state every command reaches through `get_state(ctx)`.

The root callback creates it from the global options and the injected `Runtime`. It resolves
the settings once per command (PD 10), opens stores and registers them with the typer context
(so they are closed even on errors), knows whether prompting is allowed (D3, D35) and makes sure
stdin is consumed by at most one thing (spec §6.8, generalised) and read as bytes (PD 34).
"""

from dataclasses import dataclass, field
from typing import Final

import typer

from environment_store.cli.output import err
from environment_store.cli.prompts import TerminalPrompter
from environment_store.cli.runtime import Runtime
from environment_store.config.prompt import Prompter
from environment_store.config.secrets import SecretInput
from environment_store.config.settings import Settings, resolve_settings
from environment_store.core.adapter import SetupMode
from environment_store.core.errors import ValidationError
from environment_store.library.store import EnvironmentStore

__all__ = ["CliState", "get_state"]

_WARNING_PREFIX: Final = "Warning: "


@dataclass(slots=True, kw_only=True)
class CliState:
    """The global options and boundaries of one invocation.

    Attributes:
        runtime: The terminal and OS boundaries.
        connection_option: The `-c/--connection` value, or `None`.
        use_project: `False` for `--no-project`.
        noinput: `True` for `--noinput` (D35).
    """

    runtime: Runtime
    connection_option: str | None
    use_project: bool
    noinput: bool
    _settings: Settings | None = field(default=None, init=False)
    _stores: dict[tuple[str, SetupMode], EnvironmentStore] = field(default_factory=dict, init=False)
    _stdin_claim: str | None = field(default=None, init=False)

    def settings(self) -> Settings:
        """Resolve the settings once; the first call prints each warning to stderr.

        Returns:
            The settings.

        Raises:
            ConfigurationError: An empty `-c`, a broken project file or a bad
                `ENV_STORE_ORDERED_OVERWRITE`.
        """
        if self._settings is None:
            runtime = self.runtime
            self._settings = resolve_settings(
                connection=self.connection_option,
                use_project=self.use_project,
                environ=runtime.environ(),
                cwd=runtime.cwd(),
                boundary=runtime.project_boundary,
                uid=runtime.uid,
            )
            for warning in self._settings.warnings:
                err(_WARNING_PREFIX + warning)
        return self._settings

    def open_store(
        self,
        ctx: typer.Context,
        *,
        setup: SetupMode = SetupMode.AUTO,
        connection: str | None = None,
    ) -> EnvironmentStore:
        """Open a store and close it when the command's context ends.

        The same connection and setup mode give the same `EnvironmentStore` within one
        invocation, so helpers such as `existing_secret` reuse the command's store.

        Args:
            ctx: The command's context.
            setup: How SQL backends treat their schema on open (D11, D13).
            connection: Another connection string (e.g. `cp-store --to`); `None` for the
                configured one.

        Returns:
            The open store.

        Raises:
            ConfigurationError: No connection is configured (D29).
        """
        url = self.settings().require_connection() if connection is None else connection
        key = (url, setup)
        store = self._stores.get(key)
        if store is None:
            runtime = self.runtime
            store = EnvironmentStore(
                url,
                setup=setup,
                clock=runtime.clock,
                kdf_params_factory=runtime.kdf_params_factory,
                opener=runtime.adapter_opener,
            )
            ctx.with_resource(store)
            self._stores[key] = store
        return store

    def interactive(self) -> bool:
        """Whether prompts are allowed: stdin is a terminal and `--noinput` is not set (D35)."""
        return not self.noinput and self.runtime.stdin_is_tty()

    def prompter(self) -> Prompter:
        """The prompter of this invocation (a `TerminalPrompter` unless injected)."""
        return TerminalPrompter() if self.runtime.prompter is None else self.runtime.prompter

    def secret_input(self, purpose: str) -> SecretInput:
        """What the secret resolvers of `config.secrets` may use.

        Args:
            purpose: What would read stdin, e.g. `-k -`; named if stdin is claimed twice.

        Returns:
            The TTY state, the prompter only when interactive, and a `read_stdin` that claims
            stdin before reading it.
        """

        def read_stdin() -> bytes:
            self.claim_stdin(purpose)
            return self.read_stdin_bytes()

        return SecretInput(
            read_stdin=read_stdin,
            stdin_is_tty=self.runtime.stdin_is_tty(),
            prompter=self.prompter() if self.interactive() else None,
        )

    def claim_stdin(self, purpose: str) -> None:
        """Reserve stdin for one consumer of this command.

        Args:
            purpose: What reads it, e.g. `-k -`, `--passphrase` or `the value`.

        Raises:
            ValidationError: Something else claimed it already; both are named.
        """
        if self._stdin_claim is not None:
            message = (
                f"stdin can be used only once per command: it is already used for "
                f"{self._stdin_claim}, so it cannot be used for {purpose}"
            )
            raise ValidationError(message)
        self._stdin_claim = purpose

    def read_stdin_bytes(self) -> bytes:
        """Read all of stdin as bytes (PD 34); claim it first with `claim_stdin`."""
        return typer.get_binary_stream("stdin").read()

    def read_stdin(self) -> str:
        """Read all of stdin as strict UTF-8, without newline translation (PD 34).

        Returns:
            The text exactly as sent.

        Raises:
            ValidationError: The bytes are not UTF-8.
        """
        try:
            return self.read_stdin_bytes().decode("utf-8")
        except UnicodeDecodeError:
            message = "stdin is not valid UTF-8 text"
            # Not chained: the decode error holds the raw input, which may be a secret.
            raise ValidationError(message) from None


def get_state(ctx: typer.Context) -> CliState:
    """Return the state the root callback stored in the context.

    Args:
        ctx: Any context below the root.

    Returns:
        The state.

    Raises:
        TypeError: The context does not belong to the `envs` app.
    """
    state = ctx.find_object(CliState)
    if state is None:
        message = "no CliState in this context: commands must run below the envs root callback"
        raise TypeError(message)
    return state
