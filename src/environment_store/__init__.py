"""Environment Store: named, optionally encrypted stores of environment variables."""

from importlib.metadata import version

__version__: str = version("environment-store")

__all__ = ["__version__"]
