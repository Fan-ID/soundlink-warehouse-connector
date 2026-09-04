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
SyncEntity = Literal["campaigns", "soundlinks"]


@dataclass
class SyncStats:
    entities_synced: int = 0
    entities_skipped: int = 0
    entities_resumed_skip: int = 0
    breakdown_rows: int = 0
    engagement_rows: int = 0
    windows_processed: int = 0
    errors: list[str] = field(default_factory=list)

    # Back-compat aliases used by existing campaign CLI output / tests.
    @property
    def campaigns_synced(self) -> int:
        return self.entities_synced

    @property
    def campaigns_skipped(self) -> int:
        return self.entities_skipped

    @property
    def campaigns_resumed_skip(self) -> int:
        return self.entities_resumed_skip


def metric_windows(
    created: date,
    *,
    mode: SyncMode,
    today: date,
    lookback_days: int,
) -> list[tuple[date, date]]:
    """
    Date windows to fetch for one resource.

    Incremental: lookback window clamped to created.
    Returns [] when the resource did not exist yet during the lookback (skip).
    Full: 90-day slices from created → today (empty if created > today).
    """
    if mode == "incremental":
        start, end = incremental_range(today, lookback_days)
        start = max(start, created)
        if end < start:
            return []
        return [(start, end)]
    if created > today:
        return []
    return date_windows(created, today)


def campaign_metric_windows(
    campaign: CampaignSummary,
    *,
    mode: SyncMode,
    today: date,
    lookback_days: int,
) -> list[tuple[date, date]]:
    return metric_windows(
        campaign.created_date,
        mode=mode,
        today=today,
        lookback_days=lookback_days,
    )


def _run_key(entity: SyncEntity, mode: SyncMode, sync_day: date) -> str:
    # Campaigns keep the historical key shape so in-progress resumes still work.
    if entity == "campaigns":
        return f"run:{mode}:{sync_day.isoformat()}"
    return f"run:soundlinks:{mode}:{sync_day.isoformat()}"


def _completed_field(entity: SyncEntity) -> str:
    if entity == "campaigns":
        return "completed_campaign_ids"
    return "completed_soundlink_ids"


def _last_sync_key(entity: SyncEntity) -> str:
    if entity == "campaigns":
        return "last_sync"
    return "last_sync_soundlinks"


def _completed_ids(state: StateStore, key: str, field: str) -> set[str]:
    payload = state.get(key) or {}
    raw = payload.get(field, [])
    if not isinstance(raw, list):
        return set()
    return {str(x) for x in raw}


def _save_progress(
    state: StateStore,
    run_key: str,
    *,
    entity: SyncEntity,
    mode: SyncMode,
    completed: set[str],
    error_count: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        _completed_field(entity): sorted(completed),
        "mode": mode,
        "entity": entity,
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
    soundlink_id: str | None = None,
    *,
    entity: SyncEntity = "campaigns",
    today: date | None = None,
    resume: bool = True,
) -> SyncStats:
    if entity == "campaigns" and soundlink_id is not None:
        raise ValueError("--soundlink-id requires --entity soundlinks")
    if entity == "soundlinks" and campaign_id is not None:
        raise ValueError("--campaign-id requires --entity campaigns")

    if entity == "campaigns":
        return _run_campaign_sync(
            settings,
            client,
            loader,
            state,
            mode,
            campaign_id,
            today=today,
            resume=resume,
        )
    return _run_soundlink_sync(
        settings,
        client,
        loader,
        state,
        mode,
        soundlink_id,
        today=today,
        resume=resume,
    )


def _run_campaign_sync(
    settings: Settings,
    client: SoundlinkClient,
    loader: WarehouseLoader,
    state: StateStore,
    mode: SyncMode,
    campaign_id: str | None,
    *,
    today: date | None,
    resume: bool,
) -> SyncStats:
    entity: SyncEntity = "campaigns"
    stats = SyncStats()
    sync_day = today or date.today()
    # Single-id sync must not read/write/delete org-wide resume state.
    track_org_progress = campaign_id is None
    run_key = _run_key(entity, mode, sync_day)
    completed_field = _completed_field(entity)

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

    stats.entities_synced = loader.upsert_campaigns(campaigns)
    logger.info("Upserted %s campaigns", stats.entities_synced)

    already_done = (
        _completed_ids(state, run_key, completed_field)
        if resume and track_org_progress
        else set()
    )
    completed = set(already_done)

    for campaign in campaigns:
        if campaign.campaign_id in already_done:
            stats.entities_resumed_skip += 1
            logger.info(
                "Resume: skipping %s (already completed in %s)",
                campaign.campaign_id,
                run_key,
            )
            continue

        windows = metric_windows(
            campaign.created_date,
            mode=mode,
            today=sync_day,
            lookback_days=settings.incremental_lookback_days,
        )
        if not windows:
            stats.entities_skipped += 1
            logger.info(
                "Skipping metrics for %s (no overlap with sync window; created %s)",
                campaign.campaign_id,
                campaign.created_date,
            )
            completed.add(campaign.campaign_id)
            if track_org_progress:
                _save_progress(
                    state, run_key, entity=entity, mode=mode, completed=completed
                )
            continue

        entity_ok = True
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
                entity_ok = False
                message = f"{label}: {exc}"
                logger.exception("Failed to sync window %s", label)
                stats.errors.append(message)

        if entity_ok:
            completed.add(campaign.campaign_id)
            if track_org_progress:
                _save_progress(
                    state, run_key, entity=entity, mode=mode, completed=completed
                )

    return _finish_sync(
        state,
        stats,
        entity=entity,
        mode=mode,
        sync_day=sync_day,
        run_key=run_key,
        track_org_progress=track_org_progress,
        completed=completed,
        total_entities=len(campaigns),
        single_id=campaign_id,
    )


def _run_soundlink_sync(
    settings: Settings,
    client: SoundlinkClient,
    loader: WarehouseLoader,
    state: StateStore,
    mode: SyncMode,
    soundlink_id: str | None,
    *,
    today: date | None,
    resume: bool,
) -> SyncStats:
    entity: SyncEntity = "soundlinks"
    stats = SyncStats()
    sync_day = today or date.today()
    track_org_progress = soundlink_id is None
    run_key = _run_key(entity, mode, sync_day)
    completed_field = _completed_field(entity)

    loader.ensure_schema()

    if soundlink_id:
        try:
            soundlinks = [client.get_soundlink(soundlink_id)]
        except SoundlinkApiError as exc:
            if exc.status_code == 404:
                raise ValueError(f"Soundlink not found: {soundlink_id}") from exc
            raise
    else:
        soundlinks = list(client.iter_soundlinks())

    stats.entities_synced = loader.upsert_soundlinks(soundlinks)
    logger.info("Upserted %s soundlinks", stats.entities_synced)

    already_done = (
        _completed_ids(state, run_key, completed_field)
        if resume and track_org_progress
        else set()
    )
    completed = set(already_done)

    for soundlink in soundlinks:
        if soundlink.soundlink_id in already_done:
            stats.entities_resumed_skip += 1
            logger.info(
                "Resume: skipping %s (already completed in %s)",
                soundlink.soundlink_id,
                run_key,
            )
            continue

        windows = metric_windows(
            soundlink.created_date,
            mode=mode,
            today=sync_day,
            lookback_days=settings.incremental_lookback_days,
        )
        if not windows:
            stats.entities_skipped += 1
            logger.info(
                "Skipping metrics for %s (no overlap with sync window; created %s)",
                soundlink.soundlink_id,
                soundlink.created_date,
            )
            completed.add(soundlink.soundlink_id)
            if track_org_progress:
                _save_progress(
                    state, run_key, entity=entity, mode=mode, completed=completed
                )
            continue

        entity_ok = True
        for start_date, end_date in windows:
            stats.windows_processed += 1
            label = f"{soundlink.soundlink_id} [{start_date}..{end_date}]"
            try:
                breakdown_rows, _ = client.export_metrics_jsonl(
                    soundlink_id=soundlink.soundlink_id,
                    kind="breakdown",
                    start_date=start_date,
                    end_date=end_date,
                )
                stats.breakdown_rows += loader.upsert_soundlink_breakdown_rows(
                    breakdown_rows
                )

                engagement_rows, _ = client.export_metrics_jsonl(
                    soundlink_id=soundlink.soundlink_id,
                    kind="engagement",
                    start_date=start_date,
                    end_date=end_date,
                )
                stats.engagement_rows += loader.upsert_soundlink_engagement_rows(
                    engagement_rows
                )

                logger.info(
                    "Synced %s: breakdown=%s engagement=%s",
                    label,
                    len(breakdown_rows),
                    len(engagement_rows),
                )
            except Exception as exc:
                entity_ok = False
                message = f"{label}: {exc}"
                logger.exception("Failed to sync window %s", label)
                stats.errors.append(message)

        if entity_ok:
            completed.add(soundlink.soundlink_id)
            if track_org_progress:
                _save_progress(
                    state, run_key, entity=entity, mode=mode, completed=completed
                )

    return _finish_sync(
        state,
        stats,
        entity=entity,
        mode=mode,
        sync_day=sync_day,
        run_key=run_key,
        track_org_progress=track_org_progress,
        completed=completed,
        total_entities=len(soundlinks),
        single_id=soundlink_id,
    )


def _finish_sync(
    state: StateStore,
    stats: SyncStats,
    *,
    entity: SyncEntity,
    mode: SyncMode,
    sync_day: date,
    run_key: str,
    track_org_progress: bool,
    completed: set[str],
    total_entities: int,
    single_id: str | None,
) -> SyncStats:
    label = "campaigns" if entity == "campaigns" else "soundlinks"

    if stats.errors:
        if track_org_progress:
            _save_progress(
                state,
                run_key,
                entity=entity,
                mode=mode,
                completed=completed,
                error_count=len(stats.errors),
            )
        logger.error(
            "Sync finished with %s error(s)%s (%s/%s %s)",
            len(stats.errors),
            f"; progress saved under {run_key}" if track_org_progress else "",
            len(completed),
            total_entities,
            label,
        )
        return stats

    payload: dict[str, Any] = {
        "mode": mode,
        "entity": entity,
        "date": sync_day.isoformat(),
        label: stats.entities_synced,
        "breakdown_rows": stats.breakdown_rows,
        "engagement_rows": stats.engagement_rows,
    }
    if entity == "campaigns":
        payload["campaigns"] = stats.entities_synced
        payload["campaign_id"] = single_id
    else:
        payload["soundlinks"] = stats.entities_synced
        payload["soundlink_id"] = single_id

    state.set(_last_sync_key(entity), payload)
    if track_org_progress:
        state.delete(run_key)
    state.save()
    return stats
