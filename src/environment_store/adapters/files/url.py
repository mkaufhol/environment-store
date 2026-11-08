"""Connection strings of the file adapters: `json://dir` and `toml://dir`."""

from pathlib import Path

from environment_store.core.connection import scheme_of
from environment_store.core.errors import ValidationError

__all__ = ["directory_from_url"]


def directory_from_url(url: str, *, scheme: str) -> Path:
    """Return the store directory a file connection string names.

    Path resolution mirrors SQLite: `json://relative/dir` is relative to the working directory
    at the time of the call, `json:///absolute/dir` is absolute and `json://~/dir` expands `~`.

    Args:
        url: The connection string, e.g. `json://~/envs`.
        scheme: The expected scheme (`json` or `toml`), lowercase.

    Returns:
        The absolute directory. It need not exist yet; it is created on the first write.

    Raises:
        ValidationError: The scheme differs, the path is empty or contains NUL, it has a query
            or fragment (`?`, `#`; like `sqlite://`, as options would be silently ignored), or
            `~user` names no known user.
    """
    if scheme_of(url) != scheme:
        message = f"expected a {scheme}:// connection string, e.g. {scheme}://path/to/directory"
        raise ValidationError(message)
    raw = url.partition("://")[2]
    if not raw or "\x00" in raw:
        message = f"a {scheme}:// connection string must name a directory, e.g. {scheme}://envs"
        raise ValidationError(message)
    if "?" in raw or "#" in raw:
        message = (
            f"a {scheme}:// connection string takes no query or fragment ('?', '#'); "
            f"name only the directory, e.g. {scheme}://envs"
        )
        raise ValidationError(message)
    try:
        directory = Path(raw).expanduser()
    except RuntimeError as err:
        message = f"cannot expand the home directory in the {scheme}:// connection string"
        raise ValidationError(message) from err
    return directory.absolute()
