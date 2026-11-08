"""`envs export-credentials`: the two variables that load stores in a deployment.

It prints `ENV_STORE_CONNECTION` and `ENV_STORE_LOAD`. With both set, `envs run`, every reading
command and the library's `load()` load the stores, encrypted ones included, with nothing else
configured. The stores and keys are resolved like those of every reading command, and every
store is decrypted first, so a wrong key fails here and not in the deployment.

The output holds the connection string and every key; it goes to stdout only and is never part
of an error message. A relative file path in the connection string is made absolute, because
the deployment does not start in the same directory. A first-wins merge order (from the project
file or the environment) is printed as a third variable, `ENV_STORE_ORDERED_OVERWRITE=false`, so
the deployment merges the stores the same way.
"""

import typer

from environment_store.cli.loading import reading_sources
from environment_store.cli.options import JsonOpt, ReadKeysOpt, StoresArg
from environment_store.cli.output import emit_json, out
from environment_store.cli.state import get_state
from environment_store.config.load_spec import ENV_LOAD
from environment_store.config.project import anchor_connection
from environment_store.config.settings import ENV_CONNECTION, ENV_ORDERED_OVERWRITE
from environment_store.core.errors import ValidationError
from environment_store.formats.dotenv import DotenvValueError, dumps

__all__ = ["export_credentials"]


def export_credentials(
    ctx: typer.Context,
    stores: StoresArg = None,
    *,
    keys: ReadKeysOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Print ENV_STORE_CONNECTION and ENV_STORE_LOAD for a deployment.

    With these two variables set, envs run and the library's load() load the stores, encrypted
    ones included, with nothing else configured. Every key is checked by decrypting its store. A
    first-wins merge order is printed as ENV_STORE_ORDERED_OVERWRITE=false.
    The output holds the connection string and every key: keep it in a secret manager, never in
    a file under version control.
    """
    state = get_state(ctx)
    settings = state.settings()
    environment, sources = reading_sources(ctx, stores=stores, keys=keys)
    spec = environment.load_spec(sources)
    connection = anchor_connection(settings.require_connection(), state.runtime.cwd())
    variables = {ENV_CONNECTION: connection, ENV_LOAD: spec.encode()}
    if not settings.ordered_overwrite:
        # The deployment has no project file: carry a first-wins merge order over with it.
        variables[ENV_ORDERED_OVERWRITE] = "false"
    if as_json:
        emit_json(variables)
        return
    try:
        text = dumps(variables)
    except DotenvValueError:
        message = "the connection string cannot be written as a dotenv line: use --json"
        # Not chained: the variables hold the connection string and every key.
        raise ValidationError(message) from None
    out(text, newline=False)
