"""Test backends for the file adapters: a fresh directory per backend, removed afterwards."""

import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

import pytest

from environment_store.adapters.files import open_json, open_toml
from environment_store.core.adapter import Adapter, SetupMode

__all__ = ["FileBackend", "Scheme", "file_backend"]

type Scheme = Literal["json", "toml"]


@dataclass(frozen=True, slots=True, kw_only=True)
class FileBackend:
    """A store directory reached through a `json://` or `toml://` connection string."""

    url: str
    scheme: Scheme

    def open(self, *, setup: SetupMode = SetupMode.AUTO) -> Adapter:
        opener = open_json if self.scheme == "json" else open_toml
        return opener(self.url, setup=setup)


@contextmanager
def file_backend(factory: pytest.TempPathFactory, *, scheme: Scheme) -> Generator[FileBackend]:
    root = factory.mktemp(scheme)
    # A subdirectory that does not exist yet: the adapter creates it on the first write.
    try:
        yield FileBackend(url=f"{scheme}://{root / 'stores'}", scheme=scheme)
    finally:
        shutil.rmtree(root)
