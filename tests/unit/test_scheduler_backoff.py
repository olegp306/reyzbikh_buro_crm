"""Unit tests for exponential backoff formula."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crm.scheduler.jobs import apply_backoff


def test_apply_backoff_grows_with_attempts() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    # With jitter we can't assert strict monotonicity for back-to-back
    # attempts. But attempt 3 must be >> attempt 0.
    d0 = apply_backoff(0, now=now) - now
    d3 = apply_backoff(3, now=now) - now
    assert d3 > d0 * 3  # 2^3 = 8x base, comfortably above 3x even with jitter


def test_apply_backoff_uses_minute_base() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    d0 = apply_backoff(0, now=now) - now
    assert d0 >= timedelta(seconds=60)
    assert d0 <= timedelta(seconds=60 + 15)


def test_apply_backoff_attempts_3_is_around_eight_minutes() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    d3 = apply_backoff(3, now=now) - now
    assert d3 >= timedelta(minutes=8)
    assert d3 <= timedelta(minutes=8, seconds=15)
