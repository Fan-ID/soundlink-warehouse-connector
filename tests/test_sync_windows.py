from __future__ import annotations

from datetime import UTC, date, datetime

from soundlink_warehouse_connector.client.models import CampaignSummary
from soundlink_warehouse_connector.sync.runner import campaign_metric_windows


def _campaign(*, created: date) -> CampaignSummary:
    created_at = datetime(created.year, created.month, created.day, tzinfo=UTC)
    return CampaignSummary(
        campaignId="camp-1",
        organizationId="org-1",
        status="ended",
        socialPlatform="meta",
        dailyBudget=10.0,
        totalBudget=100.0,
        campaignDuration=10,
        generation=3,
        createdAt=created_at,
        updatedAt=created_at,
    )


def test_incremental_clamps_to_created_date() -> None:
    campaign = _campaign(created=date(2026, 8, 20))
    windows = campaign_metric_windows(
        campaign,
        mode="incremental",
        today=date(2026, 8, 28),
        lookback_days=10,
    )
    assert windows == [(date(2026, 8, 20), date(2026, 8, 28))]


def test_incremental_skips_when_created_after_window() -> None:
    campaign = _campaign(created=date(2026, 8, 29))
    windows = campaign_metric_windows(
        campaign,
        mode="incremental",
        today=date(2026, 8, 28),
        lookback_days=10,
    )
    assert windows == []


def test_full_skips_when_created_after_today() -> None:
    campaign = _campaign(created=date(2026, 8, 29))
    windows = campaign_metric_windows(
        campaign,
        mode="full",
        today=date(2026, 8, 28),
        lookback_days=10,
    )
    assert windows == []
