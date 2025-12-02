"""Environment store library - Store and manage environment variables persistently."""

from environment_store.environment_store_manager import EnvironmentStoreManager, JsonFileAdapter

__version__ = "0.1.0"


__all__ = ["EnvironmentStoreManager", "JsonFileAdapter"]
