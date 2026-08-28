from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from soundlink_warehouse_connector.client.models import CampaignSummary
from soundlink_warehouse_connector.client.soundlink import SoundlinkApiError, SoundlinkClient
from soundlink_warehouse_connector.config import Settings
from soundlink_warehouse_connector.loaders.base import WarehouseLoader
from soundlink_warehouse_connector.state.store import StateStore
from soundlink_warehouse_connector.utils.dates import date_windows, incremental_range

logger = logging.getLogger(__name__)

SyncMode = Literal["full", "incremental"]


@dataclass
class SyncStats:
    campaigns_synced: int = 0
    campaigns_skipped: int = 0
    campaigns_resumed_skip: int = 0
    breakdown_rows: int = 0
    engagement_rows: int = 0
    windows_processed: int = 0
    errors: list[str] = field(default_factory=list)


def campaign_metric_windows(
    campaign: CampaignSummary,
    *,
    mode: SyncMode,
    today: date,
    lookback_days: int,
) -> list[tuple[date, date]]:
    """
    Date windows to fetch for a campaign.

    Incremental: lookback window clamped to campaign.created_date.
    Returns [] when the campaign did not exist yet during the lookback (skip).
    Full: 90-day slices from created_date → today (empty if created_date > today).
    """
    if mode == "incremental":
        start, end = incremental_range(today, lookback_days)
        start = max(start, campaign.created_date)
        if end < start:
            return []
        return [(start, end)]
    if campaign.created_date > today:
        return []
    return date_windows(campaign.created_date, today)


def _run_key(mode: SyncMode, sync_day: date) -> str:
    return f"run:{mode}:{sync_day.isoformat()}"


def _completed_campaigns(state: StateStore, key: str) -> set[str]:
    payload = state.get(key) or {}
    raw = payload.get("completed_campaign_ids", [])
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw}


def _save_progress(
    state: StateStore,
    run_key: str,
    *,
    mode: SyncMode,
    completed: set[str],
    error_count: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "completed_campaign_ids": sorted(completed),
        "mode": mode,
    }
    if error_count is not None:
        payload["error_count"] = error_count
    state.set(run_key, payload)
    state.save()


def run_sync(
    settings: Settings,
    client: SoundlinkClient,
    loader: WarehouseLoader,
    state: StateStore,
    mode: SyncMode,
    campaign_id: str | None = None,
    *,
    today: date | None = None,
    resume: bool = True,
) -> SyncStats:
    stats = SyncStats()
    sync_day = today or date.today()
    # --campaign-id must not read/write/delete org-wide resume state.
    track_org_progress = campaign_id is None
    run_key = _run_key(mode, sync_day)

    loader.ensure_schema()

    if campaign_id:
        try:
            campaigns = [client.get_campaign(campaign_id)]
        except SoundlinkApiError as exc:
            if exc.status_code == 404:
                raise ValueError(f"Campaign not found: {campaign_id}") from exc
            raise
    else:
        campaigns = list(client.iter_campaigns())

    stats.campaigns_synced = loader.upsert_campaigns(campaigns)
    logger.info("Upserted %s campaigns", stats.campaigns_synced)

    already_done = (
        _completed_campaigns(state, run_key) if resume and track_org_progress else set()
    )
    completed = set(already_done)

    for campaign in campaigns:
        if campaign.campaign_id in already_done:
            stats.campaigns_resumed_skip += 1
            logger.info(
                "Resume: skipping %s (already completed in %s)",
                campaign.campaign_id,
                run_key,
            )
            continue

        windows = campaign_metric_windows(
            campaign,
            mode=mode,
            today=sync_day,
            lookback_days=settings.incremental_lookback_days,
        )
        if not windows:
            stats.campaigns_skipped += 1
            logger.info(
                "Skipping metrics for %s (no overlap with sync window; created %s)",
                campaign.campaign_id,
                campaign.created_date,
            )
            completed.add(campaign.campaign_id)
            if track_org_progress:
                _save_progress(state, run_key, mode=mode, completed=completed)
            continue

        campaign_ok = True
        for start_date, end_date in windows:
            stats.windows_processed += 1
            label = f"{campaign.campaign_id} [{start_date}..{end_date}]"
            try:
                breakdown_rows, _ = client.export_metrics_jsonl(
                    campaign_id=campaign.campaign_id,
                    kind="breakdown",
                    start_date=start_date,
                    end_date=end_date,
                )
                stats.breakdown_rows += loader.upsert_breakdown_rows(breakdown_rows)

                engagement_rows, _ = client.export_metrics_jsonl(
                    campaign_id=campaign.campaign_id,
                    kind="engagement",
                    start_date=start_date,
                    end_date=end_date,
                )
                stats.engagement_rows += loader.upsert_engagement_rows(engagement_rows)

                logger.info(
                    "Synced %s: breakdown=%s engagement=%s",
                    label,
                    len(breakdown_rows),
                    len(engagement_rows),
                )
            except Exception as exc:
                campaign_ok = False
                message = f"{label}: {exc}"
                logger.exception("Failed to sync window %s", label)
                stats.errors.append(message)

        if campaign_ok:
            completed.add(campaign.campaign_id)
            if track_org_progress:
                _save_progress(state, run_key, mode=mode, completed=completed)

    if stats.errors:
        if track_org_progress:
            _save_progress(
                state,
                run_key,
                mode=mode,
                completed=completed,
                error_count=len(stats.errors),
            )
        logger.error(
            "Sync finished with %s error(s)%s (%s/%s campaigns)",
            len(stats.errors),
            f"; progress saved under {run_key}" if track_org_progress else "",
            len(completed),
            len(campaigns),
        )
        return stats

    state.set(
        "last_sync",
        {
            "mode": mode,
            "date": sync_day.isoformat(),
            "campaigns": stats.campaigns_synced,
            "breakdown_rows": stats.breakdown_rows,
            "engagement_rows": stats.engagement_rows,
            "campaign_id": campaign_id,
        },
    )
    if track_org_progress:
        state.delete(run_key)
    state.save()
    return stats
