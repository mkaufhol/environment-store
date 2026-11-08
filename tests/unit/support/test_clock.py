from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from tests.support.clock import DEFAULT_START, FakeClock

if TYPE_CHECKING:
    from environment_store.core.clock import Clock


def test_fake_clock_starts_at_a_fixed_aware_utc_time() -> None:
    clock = FakeClock()

    assert clock() == DEFAULT_START
    assert DEFAULT_START.tzinfo is UTC


def test_fake_clock_returns_the_same_time_until_advanced() -> None:
    clock = FakeClock()

    assert clock() == clock() == clock.now


def test_fake_clock_advance_moves_time_forward() -> None:
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC))

    clock.advance(timedelta(minutes=5))

    assert clock() == datetime(2030, 1, 1, 0, 5, tzinfo=UTC)


def test_fake_clock_with_step_advances_after_every_call() -> None:
    clock = FakeClock(datetime(2030, 1, 1, tzinfo=UTC), step=timedelta(seconds=1))

    assert [clock(), clock(), clock()] == [
        datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2030, 1, 1, 0, 0, 1, tzinfo=UTC),
        datetime(2030, 1, 1, 0, 0, 2, tzinfo=UTC),
    ]


def test_fake_clock_rejects_naive_start_times() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2030, 1, 1))  # noqa: DTZ001 - naive on purpose


def test_fake_clock_rejects_negative_steps() -> None:
    with pytest.raises(ValueError, match="must not go backwards"):
        FakeClock(step=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="must not go backwards"):
        FakeClock().advance(timedelta(seconds=-1))


def test_fake_clock_is_a_clock() -> None:
    clock: Clock = FakeClock()

    assert clock() == DEFAULT_START
