"""Concurrent writers in separate processes: the per-store lock and revision check (D7)."""

import multiprocessing
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from environment_store.core.connection import open_adapter
from environment_store.core.models import StoreRecord
from tests.adapters.files.workers import (
    COUNTER,
    CREATE_LOST,
    CREATE_WON,
    START,
    increment,
    race_create,
)

_PROCESSES: Final[int] = 3
_ROUNDS: Final[int] = 25
_JOIN_TIMEOUT: Final[float] = 120.0


def _run_processes(
    target: Callable[..., None], url: str, argument: Callable[[int], object]
) -> list[int]:
    """Start the processes together (spawn, as on macOS and Windows) and return exit codes."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(_PROCESSES)
    processes = [
        context.Process(target=target, args=(url, barrier, argument(index)))
        for index in range(_PROCESSES)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(_JOIN_TIMEOUT)
    for process in processes:
        if process.is_alive():
            process.kill()
            process.join()
    return [_exit_code(process.exitcode) for process in processes]


def _exit_code(code: int | None) -> int:
    assert code is not None, "a process did not finish"
    return code


@pytest.mark.parametrize("scheme", ["json", "toml"])
def test_writers_in_separate_processes_lose_no_update(tmp_path: Path, scheme: str) -> None:
    url = f"{scheme}://{tmp_path}"
    with open_adapter(url) as adapter:
        adapter.create_store(
            StoreRecord.plain(name=COUNTER, variables={"COUNT": "0"}, created_at=START)
        )

    exit_codes = _run_processes(increment, url, lambda _: _ROUNDS)

    assert exit_codes == [0] * _PROCESSES
    with open_adapter(url) as adapter:
        record = adapter.read_store(COUNTER)
    assert record.variables == {"COUNT": str(_PROCESSES * _ROUNDS)}
    assert record.revision == 1 + _PROCESSES * _ROUNDS
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix == ".tmp") == []


@pytest.mark.parametrize("scheme", ["json", "toml"])
def test_creates_in_separate_processes_let_exactly_one_win(tmp_path: Path, scheme: str) -> None:
    url = f"{scheme}://{tmp_path / 'new'}"

    exit_codes = _run_processes(race_create, url, lambda index: index)

    assert sorted(exit_codes) == [CREATE_WON] + [CREATE_LOST] * (_PROCESSES - 1)
    winner = exit_codes.index(CREATE_WON)
    with open_adapter(url) as adapter:
        assert adapter.read_store(COUNTER).variables == {"WINNER": str(winner)}
