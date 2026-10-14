"""Environment store library - Store and manage environment variables persistently."""

from importlib.metadata import PackageNotFoundError, version

from environment_store.core import EnvironmentStoreManager

try:
    __version__ = version("environment-store")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled source tree
    __version__ = "0.0.0"


__all__ = ["EnvironmentStoreManager"]
