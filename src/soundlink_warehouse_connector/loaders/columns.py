from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from soundlink_warehouse_connector.client.models import CampaignSummary

CAMPAIGNS_PK: tuple[str, ...] = ("campaign_id",)
BREAKDOWN_PK: tuple[str, ...] = (
    "provider",
    "account_id",
    "report_date",
    "campaign_id",
    "country_code",
)
ENGAGEMENT_PK: tuple[str, ...] = (
    "provider",
    "account_id",
    "report_date",
    "campaign_id",
    "engagement_context",
    "country_code",
    "engaged_spotify_track_id",
)

# INSERT/MERGE column order — must match DuckDB DDL and BQ schemas.
CAMPAIGNS_COLUMNS: tuple[str, ...] = (
    "campaign_id",
    "organization_id",
    "status",
    "social_platform",
    "daily_budget",
    "total_budget",
    "campaign_duration",
    "generation",
    "created_at",
    "updated_at",
    "strategy_type",
    "raw_json",
    "synced_at",
)

BREAKDOWN_COLUMNS: tuple[str, ...] = (
    "provider",
    "account_id",
    "report_date",
    "campaign_id",
    "country_code",
    "schema_version",
    "report_date_timezone",
    "exported_at",
    "campaign_name",
    "campaign_target_type",
    "campaign_target_isrc",
    "campaign_target_spotify_track_id",
    "campaign_target_playlist_id",
    "impressions",
    "ad_clicks",
    "link_clicks",
    "streams",
    "listeners",
    "followers",
    "streams_per_listener",
    "spend_media",
    "spend_total",
    "fees",
    "currency",
    "currency_account",
    "cpl",
    "cpf",
    "cpc_linkclick",
    "ctr_linkclick",
    "ctr_adclick",
    "cost_per_result",
    "result_type",
    "raw_json",
    "synced_at",
)

ENGAGEMENT_COLUMNS: tuple[str, ...] = (
    "provider",
    "account_id",
    "report_date",
    "campaign_id",
    "engagement_context",
    "country_code",
    "engaged_spotify_track_id",
    "schema_version",
    "report_date_timezone",
    "exported_at",
    "campaign_name",
    "campaign_target_type",
    "campaign_target_isrc",
    "campaign_target_spotify_track_id",
    "campaign_target_playlist_id",
    "status",
    "engaged_track_isrc",
    "engaged_track_name",
    "playlist_position",
    "new_listeners",
    "returning_listeners",
    "listeners",
    "new_listener_streams",
    "returning_listener_streams",
    "streams",
    "spl",
    "raw_json",
    "synced_at",
)


def campaign_record(
    campaign: CampaignSummary, synced_at: datetime | str
) -> dict[str, Any]:
    return {
        "campaign_id": campaign.campaign_id,
        "organization_id": campaign.organization_id,
        "status": campaign.status,
        "social_platform": campaign.social_platform,
        "daily_budget": campaign.daily_budget,
        "total_budget": campaign.total_budget,
        "campaign_duration": campaign.campaign_duration,
        "generation": campaign.generation,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "strategy_type": campaign.strategy_type,
        "raw_json": campaign.model_dump(mode="json", by_alias=True),
        "synced_at": synced_at,
    }


def breakdown_record(row: dict[str, Any], synced_at: datetime | str) -> dict[str, Any]:
    return {
        "provider": row["provider"],
        "account_id": row["account_id"],
        "report_date": row["report_date"],
        "campaign_id": row["campaign_id"],
        "country_code": row["country_code"],
        "schema_version": row.get("schema_version"),
        "report_date_timezone": row.get("report_date_timezone"),
        "exported_at": row.get("exported_at"),
        "campaign_name": row.get("campaign_name"),
        "campaign_target_type": row.get("campaign_target_type"),
        "campaign_target_isrc": row.get("campaign_target_isrc"),
        "campaign_target_spotify_track_id": row.get("campaign_target_spotify_track_id"),
        "campaign_target_playlist_id": row.get("campaign_target_playlist_id"),
        "impressions": row.get("impressions"),
        "ad_clicks": row.get("ad_clicks"),
        "link_clicks": row.get("link_clicks"),
        "streams": row.get("streams"),
        "listeners": row.get("listeners"),
        "followers": row.get("followers"),
        "streams_per_listener": row.get("streams_per_listener"),
        "spend_media": row.get("spend_media"),
        "spend_total": row.get("spend_total"),
        "fees": row.get("fees"),
        "currency": row.get("currency"),
        "currency_account": row.get("currency_account"),
        "cpl": row.get("cpl"),
        "cpf": row.get("cpf"),
        "cpc_linkclick": row.get("cpc_linkclick"),
        "ctr_linkclick": row.get("ctr_linkclick"),
        "ctr_adclick": row.get("ctr_adclick"),
        "cost_per_result": row.get("cost_per_result"),
        "result_type": row.get("result_type"),
        "raw_json": dict(row),
        "synced_at": synced_at,
    }


def engagement_record(row: dict[str, Any], synced_at: datetime | str) -> dict[str, Any]:
    return {
        "provider": row["provider"],
        "account_id": row["account_id"],
        "report_date": row["report_date"],
        "campaign_id": row["campaign_id"],
        "engagement_context": row["engagement_context"],
        "country_code": row["country_code"],
        "engaged_spotify_track_id": row["engaged_spotify_track_id"],
        "schema_version": row.get("schema_version"),
        "report_date_timezone": row.get("report_date_timezone"),
        "exported_at": row.get("exported_at"),
        "campaign_name": row.get("campaign_name"),
        "campaign_target_type": row.get("campaign_target_type"),
        "campaign_target_isrc": row.get("campaign_target_isrc"),
        "campaign_target_spotify_track_id": row.get("campaign_target_spotify_track_id"),
        "campaign_target_playlist_id": row.get("campaign_target_playlist_id"),
        "status": row.get("status"),
        "engaged_track_isrc": row.get("engaged_track_isrc"),
        "engaged_track_name": row.get("engaged_track_name"),
        "playlist_position": row.get("playlist_position"),
        "new_listeners": row.get("new_listeners"),
        "returning_listeners": row.get("returning_listeners"),
        "listeners": row.get("listeners"),
        "new_listener_streams": row.get("new_listener_streams"),
        "returning_listener_streams": row.get("returning_listener_streams"),
        "streams": row.get("streams"),
        "spl": row.get("spl"),
        "raw_json": dict(row),
        "synced_at": synced_at,
    }


def as_tuple(record: dict[str, Any], columns: tuple[str, ...]) -> tuple[Any, ...]:
    """DuckDB bind values; raw_json is stored as a JSON text string."""
    values: list[Any] = []
    for column in columns:
        value = record[column]
        if column == "raw_json" and not isinstance(value, str):
            value = json.dumps(value)
        values.append(value)
    return tuple(values)


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
