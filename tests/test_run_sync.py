from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soundlink_warehouse_connector.client.models import CampaignSummary, SoundlinkSummary
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


def _soundlink(
    soundlink_id: str = "sl-1",
    *,
    created: date = date(2026, 8, 1),
) -> SoundlinkSummary:
    created_at = datetime(created.year, created.month, created.day, tzinfo=UTC)
    return SoundlinkSummary(
        soundlinkId=soundlink_id,
        organizationId="org-1",
        name="Midnight Drive",
        url=f"https://sndl.ink/soundlink/{soundlink_id}",
        targetType="track",
        spotifyUrl="https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl",
        status="active",
        createdAt=created_at,
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
    loader.upsert_soundlinks.side_effect = lambda items: len(items)
    loader.upsert_soundlink_breakdown_rows.side_effect = lambda rows: len(rows)
    loader.upsert_soundlink_engagement_rows.side_effect = lambda rows: len(rows)
    loader.upsert_soundlink_retention_rows.side_effect = lambda rows: len(rows)
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


def test_run_sync_resume_skips_completed_soundlinks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    state.set(
        "run:soundlinks:incremental:2026-08-28",
        {"completed_soundlink_ids": ["sl-1"], "mode": "incremental"},
    )
    state.save()

    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1"), _soundlink("sl-2")])
    client.export_metrics_jsonl.return_value = ([], 0)
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
        resume=True,
    )

    assert stats.entities_resumed_skip == 1
    # sl-2 only: 1 window → 2 batch calls (breakdown + retention) + 1 engagement call
    assert client.export_soundlink_metrics_batch_jsonl.call_count == 2
    for call in client.export_soundlink_metrics_batch_jsonl.call_args_list:
        assert call.kwargs["soundlink_ids"] == ["sl-2"]
    assert client.export_metrics_jsonl.call_count == 1
    for call in client.export_metrics_jsonl.call_args_list:
        assert call.kwargs["soundlink_id"] == "sl-2"
        assert "campaign_id" not in call.kwargs or call.kwargs.get("campaign_id") is None
    assert stats.errors == []
    assert state.get("last_sync_soundlinks") is not None
    assert state.get("run:soundlinks:incremental:2026-08-28") is None


def test_run_sync_soundlinks_uses_separate_resume_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    state.set(
        "run:incremental:2026-08-28",
        {"completed_campaign_ids": ["camp-1"], "mode": "incremental"},
    )
    state.save()

    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1"), _soundlink("sl-2")])
    client.export_metrics_jsonl.return_value = ([], 0)
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
        resume=True,
    )

    assert stats.entities_synced == 2
    assert stats.entities_resumed_skip == 0
    # Both soundlinks chunk into one batch, one window → 2 batch calls (breakdown + retention)
    assert client.export_soundlink_metrics_batch_jsonl.call_count == 2
    for call in client.export_soundlink_metrics_batch_jsonl.call_args_list:
        assert set(call.kwargs["soundlink_ids"]) == {"sl-1", "sl-2"}
    # Engagement stays per-soundlink: one call per id for the shared window
    assert client.export_metrics_jsonl.call_count == 2
    assert state.get("last_sync_soundlinks") is not None
    assert state.get("run:soundlinks:incremental:2026-08-28") is None
    # Campaign resume state untouched.
    assert state.get("run:incremental:2026-08-28") == {
        "completed_campaign_ids": ["camp-1"],
        "mode": "incremental",
    }


def test_run_sync_soundlinks_retention_batch_uses_group_by_country(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1")])
    client.export_metrics_jsonl.return_value = ([], 0)
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)
    loader = _loader()

    run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    kinds = {
        call.kwargs["kind"]: call.kwargs.get("group_by")
        for call in client.export_soundlink_metrics_batch_jsonl.call_args_list
    }
    assert kinds == {"breakdown": None, "retention": "country"}


def test_run_sync_soundlinks_chunks_into_batches_of_50(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    soundlinks = [_soundlink(f"sl-{i}") for i in range(51)]
    client = MagicMock()
    client.iter_soundlinks.return_value = iter(soundlinks)
    client.export_metrics_jsonl.return_value = ([], 0)
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)
    loader = _loader()

    run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    breakdown_calls = [
        call
        for call in client.export_soundlink_metrics_batch_jsonl.call_args_list
        if call.kwargs["kind"] == "breakdown"
    ]
    batch_sizes = sorted(len(call.kwargs["soundlink_ids"]) for call in breakdown_calls)
    assert batch_sizes == [1, 50]


def test_run_sync_soundlinks_premium_retention_does_not_fail_sync(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1")])
    client.export_metrics_jsonl.return_value = ([], 0)

    def _batch(*, kind: str, **_kwargs: object) -> tuple[list, int]:
        if kind == "retention":
            raise SoundlinkApiError(
                "POST /v1/soundlinks/metrics/retention/export/batch failed with 403",
                status_code=403,
                body='{"error":{"code":"premium_plan_required"}}',
            )
        return [{"soundlink_id": "sl-1"}], 1

    client.export_soundlink_metrics_batch_jsonl.side_effect = _batch
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    assert stats.errors == []
    assert stats.retention_rows == 0
    assert loader.upsert_soundlink_breakdown_rows.called
    assert not loader.upsert_soundlink_retention_rows.called
    assert client.export_metrics_jsonl.call_count == 1
    last = state.get("last_sync_soundlinks")
    assert last is not None
    assert last["retention_rows"] == 0
    assert last["breakdown_rows"] == 1


def test_run_sync_soundlinks_breakdown_failure_skips_engagement(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1"), _soundlink("sl-2")])
    client.export_soundlink_metrics_batch_jsonl.side_effect = RuntimeError("batch boom")
    client.export_metrics_jsonl.return_value = ([], 0)
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    assert len(stats.errors) == 1
    client.export_metrics_jsonl.assert_not_called()
    assert state.get("last_sync_soundlinks") is None


def test_run_sync_soundlinks_incremental_uses_shared_lookback_not_min_created(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_soundlinks.return_value = iter(
        [
            _soundlink("sl-old", created=date(2025, 1, 1)),
            _soundlink("sl-new", created=date(2026, 8, 20)),
        ]
    )
    client.export_metrics_jsonl.return_value = ([], 0)
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)
    loader = _loader()

    run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    breakdown = next(
        call
        for call in client.export_soundlink_metrics_batch_jsonl.call_args_list
        if call.kwargs["kind"] == "breakdown"
    )
    # lookback_days=10 → 2026-08-19 .. 2026-08-28 (not from 2025-01-01)
    assert breakdown.kwargs["start_date"] == date(2026, 8, 19)
    assert breakdown.kwargs["end_date"] == date(2026, 8, 28)


def test_run_sync_soundlinks_partial_engagement_failure_marks_only_failed_id(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    client.iter_soundlinks.return_value = iter([_soundlink("sl-1"), _soundlink("sl-2")])
    client.export_soundlink_metrics_batch_jsonl.return_value = ([], 0)

    def _engagement(*, soundlink_id: str, **_kwargs: object) -> tuple[list, int]:
        if soundlink_id == "sl-1":
            raise RuntimeError("boom")
        return [], 0

    client.export_metrics_jsonl.side_effect = _engagement
    loader = _loader()

    stats = run_sync(
        settings,
        client,
        loader,
        state,
        "incremental",
        entity="soundlinks",
        today=date(2026, 8, 28),
    )

    assert len(stats.errors) == 1
    progress = state.get("run:soundlinks:incremental:2026-08-28")
    assert progress is not None
    assert progress["completed_soundlink_ids"] == ["sl-2"]
    assert state.get("last_sync_soundlinks") is None


def test_run_sync_rejects_crossed_entity_ids(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    state = StateStore(settings.state_path)
    client = MagicMock()
    loader = _loader()

    with pytest.raises(ValueError, match="--soundlink-id requires"):
        run_sync(
            settings,
            client,
            loader,
            state,
            "incremental",
            soundlink_id="sl-1",
            entity="campaigns",
        )

    with pytest.raises(ValueError, match="--campaign-id requires"):
        run_sync(
            settings,
            client,
            loader,
            state,
            "incremental",
            campaign_id="camp-1",
            entity="soundlinks",
        )
