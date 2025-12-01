"""
Adapter module for environment store storage backends.

This module provides the abstract base class and concrete implementations
for storage adapters used by the EnvironmentStoreManager.
"""

from .abstract_adapter import AbstractAdapter

__all__ = ["AbstractAdapter"]
