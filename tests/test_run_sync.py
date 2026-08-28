from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soundlink_warehouse_connector.client.models import CampaignSummary
from soundlink_warehouse_connector.client.soundlink import SoundlinkApiError
from soundlink_warehouse_connector.config import Destination, Settings
from soundlink_warehouse_connector.state.store import StateStore
from soundlink_warehouse_connector.sync.runner import run_sync


def _campaign(
    campaign_id: str = "camp-1",
    *,
    created: date = date(2026, 8, 1),
) -> CampaignSummary:
    created_at = datetime(created.year, created.month, created.day, tzinfo=UTC)
    return CampaignSummary(
        campaignId=campaign_id,
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


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        soundlink_api_key="sk_test_ok",
        destination=Destination.DUCKDB,
        duckdb_path=tmp_path / "t.duckdb",
        state_path=tmp_path / "state.json",
        incremental_lookback_days=10,
    )


def _loader() -> MagicMock:
    loader = MagicMock()
    loader.upsert_campaigns.side_effect = lambda camps: len(camps)
    loader.upsert_breakdown_rows.side_effect = lambda rows: len(rows)
    loader.upsert_engagement_rows.side_effect = lambda rows: len(rows)
    return loader


def test_run_sync_uses_get_campaign_for_campaign_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    # Org-wide progress must survive a successful --campaign-id run.
    state.set(
        "run:incremental:2026-08-28",
        {"completed_campaign_ids": ["other-camp"], "mode": "incremental"},
    )
    state.save()

    client = MagicMock()
    campaign = _campaign()
    client.get_campaign.return_value = campaign
    client.export_metrics_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        campaign_id="camp-1",
        today=date(2026, 8, 28),
    )

    client.get_campaign.assert_called_once_with("camp-1")
    client.iter_campaigns.assert_not_called()
    assert stats.campaigns_synced == 1
    assert stats.campaigns_resumed_skip == 0
    assert stats.errors == []
    assert state.get("last_sync") is not None
    assert state.get("last_sync")["campaign_id"] == "camp-1"
    assert state.get("run:incremental:2026-08-28") == {
        "completed_campaign_ids": ["other-camp"],
        "mode": "incremental",
    }


def test_run_sync_campaign_id_ignores_org_resume(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    state.set(
        "run:incremental:2026-08-28",
        {"completed_campaign_ids": ["camp-1"], "mode": "incremental"},
    )
    state.save()

    client = MagicMock()
    client.get_campaign.return_value = _campaign("camp-1")
    client.export_metrics_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        campaign_id="camp-1",
        today=date(2026, 8, 28),
        resume=True,
    )

    assert stats.campaigns_resumed_skip == 0
    assert client.export_metrics_jsonl.call_count == 2


def test_run_sync_get_campaign_404_raises(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.get_campaign.side_effect = SoundlinkApiError("missing", status_code=404)
    loader = _loader()

    with pytest.raises(ValueError, match="Campaign not found"):
        run_sync(
            settings,
            client,
            loader,
            state,
            "incremental",
            campaign_id="missing",
            today=date(2026, 8, 28),
        )


def test_run_sync_resume_skips_completed_campaigns(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    state.set(
        "run:incremental:2026-08-28",
        {"completed_campaign_ids": ["camp-1"], "mode": "incremental"},
    )
    state.save()

    client = MagicMock()
    client.iter_campaigns.return_value = iter([_campaign("camp-1"), _campaign("camp-2")])
    client.export_metrics_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        today=date(2026, 8, 28),
        resume=True,
    )

    assert stats.campaigns_resumed_skip == 1
    # camp-2 only: 2 exports (breakdown + engagement) for one window
    assert client.export_metrics_jsonl.call_count == 2
    assert stats.errors == []
    assert state.get("last_sync") is not None
    assert state.get("run:incremental:2026-08-28") is None


def test_run_sync_does_not_set_last_sync_on_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_campaigns.return_value = iter([_campaign("camp-1")])
    client.export_metrics_jsonl.side_effect = RuntimeError("boom")
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        today=date(2026, 8, 28),
    )

    assert len(stats.errors) == 1
    assert state.get("last_sync") is None
    progress = state.get("run:incremental:2026-08-28")
    assert progress is not None
    assert progress["completed_campaign_ids"] == []
    assert progress["error_count"] == 1


def test_run_sync_skips_no_window_overlap_and_marks_complete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    # created after lookback end relative to today
    client.iter_campaigns.return_value = iter(
        [_campaign("camp-new", created=date(2026, 8, 29))]
    )
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        today=date(2026, 8, 28),
    )

    assert stats.campaigns_skipped == 1
    client.export_metrics_jsonl.assert_not_called()
    assert state.get("last_sync") is not None
