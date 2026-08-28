from __future__ import annotations

from datetime import date, timedelta

MAX_EXPORT_DAYS = 90


def date_windows(
    start: date, end: date, max_days: int = MAX_EXPORT_DAYS
) -> list[tuple[date, date]]:
    """Split [start, end] into inclusive windows of at most max_days each."""
    if end < start:
        raise ValueError(f"endDate {end} is before startDate {start}")
    windows: list[tuple[date, date]] = []
    cursor = start
    # API allows inclusive ranges of at most 90 calendar days
    span_limit = max_days - 1
    while cursor <= end:
        window_end = min(cursor + timedelta(days=span_limit), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def incremental_range(today: date, lookback_days: int) -> tuple[date, date]:
    """Inclusive window of `lookback_days` calendar days ending today."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    start = today - timedelta(days=lookback_days - 1)
    return start, today
