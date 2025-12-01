"""
Environment Variables Manager module.

This module provides a high-level interface for managing environment variables
on AWS using either Parameter Store or Secrets Manager as the backend.
"""

from .environment_variables_manager import EnvironmentVariablesManager
from .abstract_adapter import EnvironmentVariablesManagerAdapter
from .parameter_store_adapter import ParameterStoreAdapter
from .secrets_manager_adapter import SecretsManagerAdapter

__all__ = [
    "EnvironmentVariablesManager",
    "EnvironmentVariablesManagerAdapter",
    "ParameterStoreAdapter",
    "SecretsManagerAdapter",
]
