from __future__ import annotations

from datetime import date

import pytest

from soundlink_warehouse_connector.utils.dates import date_windows, incremental_range


def test_incremental_range_is_inclusive() -> None:
    today = date(2026, 4, 10)
    start, end = incremental_range(today, lookback_days=10)
    assert start == date(2026, 4, 1)
    assert end == today
    assert (end - start).days + 1 == 10


def test_incremental_range_one_day() -> None:
    today = date(2026, 4, 10)
    assert incremental_range(today, lookback_days=1) == (today, today)


def test_date_windows_single_window() -> None:
    start = date(2026, 1, 1)
    end = date(2026, 1, 30)
    assert date_windows(start, end) == [(start, end)]


def test_date_windows_splits_at_90_days() -> None:
    start = date(2026, 1, 1)
    end = date(2026, 6, 1)
    windows = date_windows(start, end)
    assert windows[0] == (date(2026, 1, 1), date(2026, 3, 31))
    assert windows[1] == (date(2026, 4, 1), date(2026, 6, 1))
    for window_start, window_end in windows:
        assert (window_end - window_start).days <= 89


def test_date_windows_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="before startDate"):
        date_windows(date(2026, 2, 1), date(2026, 1, 1))
