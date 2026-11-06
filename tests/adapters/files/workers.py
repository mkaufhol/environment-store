"""Worker functions run in separate processes (multiprocessing, spawn) by test_processes.py.

They live in an importable module because spawned children import their target by name.
"""

import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from environment_store.core.connection import open_adapter
from environment_store.core.errors import ConcurrentModificationError, StoreExistsError
from environment_store.core.models import StoreRecord

if TYPE_CHECKING:
    from multiprocessing.synchronize import Barrier

__all__ = ["COUNTER", "CREATE_LOST", "CREATE_WON", "START", "increment", "race_create"]

COUNTER: Final[str] = "counter"
START: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)
CREATE_WON: Final[int] = 0
CREATE_LOST: Final[int] = 3
_BARRIER_TIMEOUT: Final[float] = 60.0


def increment(url: str, barrier: "Barrier", rounds: int) -> None:
    """Increment `COUNT` of the counter store `rounds` times, retrying on conflicts (D7)."""
    with open_adapter(url) as adapter:
        barrier.wait(_BARRIER_TIMEOUT)
        done = 0
        while done < rounds:
            record = adapter.read_store(COUNTER)
            count = int((record.variables or {})["COUNT"])
            updated = StoreRecord.plain(
                name=COUNTER,
                variables={"COUNT": str(count + 1)},
                revision=record.revision + 1,
                created_at=record.created_at,
                updated_at=record.updated_at + timedelta(microseconds=1),
            )
            try:
                adapter.write_store(updated, expected_revision=record.revision)
            except ConcurrentModificationError:
                continue
            done += 1


def race_create(url: str, barrier: "Barrier", racer: int) -> None:
    """Try to create the counter store; the exit code tells whether this process won."""
    record = StoreRecord.plain(name=COUNTER, variables={"WINNER": str(racer)}, created_at=START)
    with open_adapter(url) as adapter:
        barrier.wait(_BARRIER_TIMEOUT)
        try:
            adapter.create_store(record)
        except StoreExistsError:
            sys.exit(CREATE_LOST)
    sys.exit(CREATE_WON)
