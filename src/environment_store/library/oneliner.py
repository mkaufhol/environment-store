"""`load()`: the one-liner that resolves configuration like the CLI and fills `os.environ` (D36).

Like python-dotenv's `load_dotenv()`: connection, project file, stores and keys are resolved
exactly as the CLI does (spec §5, §6.0.3), encrypted stores are prompted for on a terminal
(D3, PD 11, never with `noinput`, D35) and variables already in the environment are kept unless
`overwrite` is set (PD 14). `load_with` is the same with every boundary injected.
"""

import os
import sys
import warnings
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path

from environment_store.config.prompt import GetpassPrompter, Prompter
from environment_store.config.secrets import KeyFile, SecretInput, SecretResolver, no_stdin
from environment_store.config.settings import (
    CredentialsInProjectFileWarning,
    Settings,
    resolve_settings,
)
from environment_store.core.errors import (
    ConfigurationError,
    KeyRequiredError,
    NotEncryptedError,
    ValidationError,
)
from environment_store.core.secrets import Secret
from environment_store.core.validation import validate_store_name
from environment_store.library.environment import Environment
from environment_store.library.sources import KeyInput, Source, check_key_input
from environment_store.library.store import (
    AdapterOpener,
    EnvironmentStore,
    open_configured_adapter,
)

__all__ = ["load", "load_with"]


def load(  # noqa: PLR0913 - the keyword-only options of D36
    *stores: str,
    connection: str | None = None,
    keys: Mapping[str, KeyInput] | None = None,
    first_wins: bool = False,
    overwrite: bool = False,
    nested: bool = False,
    use_project: bool = True,
    noinput: bool = False,
) -> Environment:
    """Load stores into `os.environ`, configured like the CLI (D36).

    Args:
        *stores: Stores in load order; none uses the project file's `stores`.
        connection: The connection string; `None` uses `ENV_STORE_CONNECTION`, then the
            project file.
        keys: Store name → key; beats the project file's `[keys]`.
        first_wins: The first store wins instead of the last (beats every other setting).
        overwrite: Replace variables already in `os.environ`.
        nested: Set prefixed names (`STORE__NAME`, D30) instead of merging.
        use_project: `False` ignores `.envstore.toml`.
        noinput: Never prompt, even on a terminal (D35).

    Returns:
        The loaded stores.

    Raises:
        ConfigurationError: No connection, no stores, or a broken project file.
        KeyRequiredError: An encrypted store has no key and prompting is not possible.
    """
    stdin = sys.stdin
    return load_with(
        stores,
        connection=connection,
        keys=keys,
        first_wins=first_wins,
        overwrite=overwrite,
        nested=nested,
        use_project=use_project,
        noinput=noinput,
        environ=os.environ,
        cwd=Path.cwd(),
        interactive=stdin is not None and stdin.isatty(),
        prompter=GetpassPrompter(),
        target=os.environ,
    )


def load_with(  # noqa: PLR0913 - every boundary is injected
    stores: Sequence[str],
    *,
    connection: str | None,
    keys: Mapping[str, KeyInput] | None,
    first_wins: bool,
    overwrite: bool,
    nested: bool,
    use_project: bool,
    noinput: bool,
    environ: Mapping[str, str],
    cwd: Path,
    interactive: bool,
    prompter: Prompter,
    target: MutableMapping[str, str],
    boundary: Path | None = None,
    uid: int | None = None,
    opener: AdapterOpener = open_configured_adapter,
) -> Environment:
    """`load` with its boundaries injected.

    Args:
        stores: Stores in load order; empty uses the project file's `stores`.
        connection: As for `load`.
        keys: As for `load`.
        first_wins: As for `load`.
        overwrite: As for `load`.
        nested: As for `load`.
        use_project: As for `load`.
        noinput: As for `load`.
        environ: The environment variables that configure the run.
        cwd: Where the project file search starts.
        interactive: Whether stdin is a terminal.
        prompter: Asks for keys when interactive and not `noinput`.
        target: Where the variables are applied.
        boundary: The last directory of the project file search.
        uid: The owner a project file must have (PD 32); `None` for the effective user.
        opener: Opens the adapter.

    Returns:
        The loaded stores.

    Raises:
        ConfigurationError: An empty `connection`; otherwise as for `load`.
    """
    if connection == "":
        # Checked here: the settings layer words this for the CLI's -c option (D47).
        message = "connection must not be empty: pass a connection string, or None to configure it"
        raise ConfigurationError(message)
    settings = resolve_settings(
        connection=connection,
        use_project=use_project,
        environ=environ,
        cwd=cwd,
        boundary=boundary,
        uid=uid,
    )
    for message in settings.warnings:
        warnings.warn(message, CredentialsInProjectFileWarning, stacklevel=3)
    names = _store_names(stores, settings)
    explicit = _explicit_keys(keys, names)
    secret_input = SecretInput(
        read_stdin=no_stdin,
        stdin_is_tty=interactive,
        prompter=prompter if interactive and not noinput else None,
    )
    unique = tuple(dict.fromkeys(names))
    with EnvironmentStore.from_settings(settings, opener=opener) as store:
        # Like the CLI (PD 18): every store must exist before a key is read or prompted for,
        # so a typo never costs a prompt.
        for name in unique:
            store.store_info(name)
        resolver = SecretResolver(store, secret_input)
        secrets = {
            name: _secret(store, resolver, name, explicit.get(name), settings) for name in unique
        }
        environment = store.load(
            [Source(name, key=secrets[name]) for name in names],
            order=settings.merge_order(first_wins=first_wins),
        )
    environment.apply(overwrite=overwrite, nested=nested, environ=target)
    return environment


def _store_names(stores: Sequence[str], settings: Settings) -> tuple[str, ...]:
    names = tuple(stores) or settings.stores
    if not names:
        message = (
            "no stores to load: name them, e.g. load('base_conf'), or set 'stores' in "
            ".envstore.toml"
        )
        raise ConfigurationError(message)
    for name in names:
        validate_store_name(name)
    return names


def _explicit_keys(
    keys: Mapping[str, KeyInput] | None, names: Sequence[str]
) -> Mapping[str, KeyInput]:
    given = {} if keys is None else keys
    unused = sorted(set(given) - set(names))
    if unused:
        message = f"a key was given for store {unused[0]!r}, which is not loaded"
        raise ValidationError(message)
    for key in given.values():
        check_key_input(key)
    return given


def _secret(
    store: EnvironmentStore,
    resolver: SecretResolver,
    name: str,
    key: KeyInput | None,
    settings: Settings,
) -> Secret | None:
    if key is not None:
        return store.secret_for(name, key)
    path = settings.key_paths.get(name)
    if path is None:
        try:
            return resolver.existing(name, None)
        except KeyRequiredError as err:
            # The resolver words this for the CLI (-k); the library names its parameters (D47).
            raise KeyRequiredError.for_store(name) from err
    try:
        return resolver.existing(name, KeyFile(path))
    except NotEncryptedError as err:
        # Keys are bound by store name, so a project key for a used plaintext store is an error
        # (PD 5); the user gave no key, so the message points at where it came from.
        message = (
            f"[keys] in '{settings.project_file}' names a key for store {name!r}, which is not "
            "encrypted: remove the entry"
        )
        raise NotEncryptedError(message) from err
