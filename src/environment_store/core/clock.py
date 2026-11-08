"""Clock abstraction, so that timestamps can be injected in tests."""

from collections.abc import Callable
from datetime import UTC, datetime

__all__ = ["Clock", "utc_now"]

type Clock = Callable[[], datetime]
"""A function returning the current time as a timezone-aware UTC `datetime`."""


def utc_now() -> datetime:
    """Return the current time.

    Returns:
        The current time as a timezone-aware UTC `datetime`.
    """
    return datetime.now(UTC)
