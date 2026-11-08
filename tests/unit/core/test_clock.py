from datetime import UTC, datetime, timedelta

from environment_store.core.clock import Clock, utc_now


def test_utc_now_returns_an_aware_utc_datetime() -> None:
    now = utc_now()

    assert now.tzinfo is UTC


def test_utc_now_returns_the_current_time() -> None:
    before = datetime.now(UTC)
    now = utc_now()
    after = datetime.now(UTC)

    assert before <= now <= after
    assert after - before < timedelta(seconds=5)


def test_utc_now_is_a_clock() -> None:
    clock: Clock = utc_now

    assert clock().utcoffset() == timedelta(0)
