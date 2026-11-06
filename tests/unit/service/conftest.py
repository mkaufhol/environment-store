"""Fixtures and fakes for the `StoreService` tests: a memory backend, a fake clock, cheap KDFs."""

from collections.abc import Callable
from datetime import timedelta
from types import TracebackType
from typing import Final, NoReturn, Self

import pytest

from environment_store.core.errors import BackendError
from environment_store.core.models import KdfParams, StoreInfo, StoreRecord
from environment_store.core.secrets import KeyMaterial, Passphrase
from environment_store.service import StoreService
from tests.support.clock import FakeClock
from tests.support.memory_adapter import MemoryAdapter, MemoryBackend

KEY: Final = KeyMaterial(key=b"\x01" * 32)
OTHER_KEY: Final = KeyMaterial(key=b"\x02" * 32)
PASSPHRASE: Final = Passphrase(text="correct horse battery staple")
OTHER_PASSPHRASE: Final = Passphrase(text="Tr0ub4dor&3")


class CheapKdf:
    """A `kdf_params_factory` with the cheapest Argon2id parameters and a new salt per call."""

    calls: int

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> KdfParams:
        self.calls += 1
        return KdfParams(iterations=1, memory_kib=8, lanes=1, salt=self.calls.to_bytes(16, "big"))


class UntouchableAdapter:
    """An adapter that fails the test on any use: proves validation happens before I/O."""

    def list_stores(self) -> list[StoreInfo]:
        _touched()

    def create_store(self, record: StoreRecord) -> None:
        _touched()

    def read_store(self, name: str) -> StoreRecord:
        _touched()

    def write_store(self, record: StoreRecord, *, expected_revision: int) -> None:
        _touched()

    def delete_store(self, name: str) -> None:
        _touched()

    def close(self) -> None:
        _touched()

    def __enter__(self) -> Self:
        _touched()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _touched()


def _touched() -> NoReturn:
    message = "the adapter must not be touched"
    raise AssertionError(message)


class RacingAdapter(MemoryAdapter):
    """Runs `race` once, right after the first `read_store`: a concurrent writer."""

    race: Callable[[MemoryBackend], None] | None

    def __init__(self, backend: MemoryBackend, race: Callable[[MemoryBackend], None]) -> None:
        super().__init__(backend)
        self.race = race

    def read_store(self, name: str) -> StoreRecord:
        record = super().read_store(name)
        if self.race is not None:
            race, self.race = self.race, None
            race(self.backend)
        return record


class FailingDeleteAdapter(MemoryAdapter):
    """A memory adapter whose `delete_store` always fails like a broken backend."""

    def delete_store(self, name: str) -> None:
        message = "backend unavailable"
        raise BackendError(message)


def bump(name: str) -> Callable[[MemoryBackend], None]:
    """A concurrent writer that rewrites `name` unchanged at the next revision."""

    def race(backend: MemoryBackend) -> None:
        record = backend.read(name)
        newer = StoreRecord(
            name=record.name,
            revision=record.revision + 1,
            created_at=record.created_at,
            updated_at=record.updated_at,
            variables=record.variables,
            ciphertext=record.ciphertext,
            cipher_meta=record.cipher_meta,
        )
        backend.replace(newer, expected_revision=record.revision)

    return race


@pytest.fixture
def backend() -> MemoryBackend:
    return MemoryBackend()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(step=timedelta(seconds=1))


@pytest.fixture
def kdf() -> CheapKdf:
    return CheapKdf()


@pytest.fixture
def make_service(clock: FakeClock, kdf: CheapKdf) -> Callable[[MemoryAdapter], StoreService]:
    def make(adapter: MemoryAdapter) -> StoreService:
        return StoreService(adapter, clock=clock, kdf_params_factory=kdf)

    return make


@pytest.fixture
def service(
    backend: MemoryBackend, make_service: Callable[[MemoryAdapter], StoreService]
) -> StoreService:
    return make_service(backend.open())
