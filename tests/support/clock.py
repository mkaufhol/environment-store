"""Deterministic fake clock for tests that check timestamps."""

from datetime import UTC, datetime, timedelta
from typing import Final

__all__ = ["DEFAULT_START", "FakeClock"]

DEFAULT_START: Final[datetime] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


class FakeClock:
    """A `Clock` that returns a controlled time.

    Every call returns the current time and then moves it forward by `step` (default: not at
    all). `advance` moves it explicitly.
    """

    _now: datetime
    _step: timedelta

    def __init__(self, start: datetime = DEFAULT_START, *, step: timedelta = timedelta(0)) -> None:
        if start.utcoffset() is None:
            message = "the fake clock needs a timezone-aware start time"
            raise ValueError(message)
        _check_forward(step)
        self._now = start.astimezone(UTC)
        self._step = step

    def __call__(self) -> datetime:
        now = self._now
        self._now += self._step
        return now

    @property
    def now(self) -> datetime:
        """The time the next call returns, without advancing."""
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the time forward by `delta`."""
        _check_forward(delta)
        self._now += delta


def _check_forward(delta: timedelta) -> None:
    if delta < timedelta(0):
        message = "the fake clock must not go backwards"
        raise ValueError(message)
