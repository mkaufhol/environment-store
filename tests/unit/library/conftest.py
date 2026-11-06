"""Fixtures for the library tests: an `EnvironmentStore` on a memory backend, keys, key files."""

from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Final

import pytest

from environment_store.core.adapter import Adapter, SetupMode
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.crypto.keyfile import format_key
from environment_store.library.store import EnvironmentStore
from tests.support.clock import FakeClock
from tests.support.kdf import CheapKdf
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend

KEY: Final = KeyMaterial(key=b"\x01" * 32)
OTHER_KEY: Final = KeyMaterial(key=b"\x02" * 32)
PASSPHRASE: Final = Passphrase(text="correct horse battery staple")
CONNECTION: Final = "memory://test"

type Opener = Callable[[str, SetupMode], Adapter]


class RecordingOpener:
    """An `AdapterOpener` on a memory backend that remembers every adapter it opened."""

    backend: MemoryBackend
    opened: list[tuple[str, SetupMode, MemoryAdapter]]

    def __init__(self, backend: MemoryBackend) -> None:
        self.backend = backend
        self.opened = []

    def __call__(self, url: str, setup: SetupMode) -> MemoryAdapter:
        adapter = self.backend.open(setup=setup)
        self.opened.append((url, setup, adapter))
        return adapter


@pytest.fixture
def backend() -> MemoryBackend:
    return MemoryBackend()


@pytest.fixture
def opener(backend: MemoryBackend) -> RecordingOpener:
    return RecordingOpener(backend)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(step=timedelta(seconds=1))


@pytest.fixture
def kdf() -> CheapKdf:
    return CheapKdf()


@pytest.fixture
def make_store(
    opener: RecordingOpener, clock: FakeClock, kdf: CheapKdf
) -> Iterator[Callable[[], EnvironmentStore]]:
    made: list[EnvironmentStore] = []

    def make() -> EnvironmentStore:
        store = EnvironmentStore(CONNECTION, clock=clock, kdf_params_factory=kdf, opener=opener)
        made.append(store)
        return store

    yield make
    for store in made:
        store.close()


@pytest.fixture
def store(make_store: Callable[[], EnvironmentStore]) -> EnvironmentStore:
    return make_store()


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / "a.key"
    path.write_text(format_key(KEY), encoding="ascii")
    return path


@pytest.fixture
def other_key_file(tmp_path: Path) -> Path:
    path = tmp_path / "other.key"
    path.write_text(format_key(OTHER_KEY), encoding="ascii")
    return path


@pytest.fixture
def passphrase_file(tmp_path: Path) -> Path:
    path = tmp_path / "pass.txt"
    path.write_text(f"{PASSPHRASE.text}\n", encoding="utf-8")
    return path
