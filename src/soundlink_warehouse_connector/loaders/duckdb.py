from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from soundlink_warehouse_connector.client.models import CampaignSummary, SoundlinkSummary
from soundlink_warehouse_connector.loaders.base import WarehouseLoader
from soundlink_warehouse_connector.loaders.columns import (
    BREAKDOWN_COLUMNS,
    CAMPAIGNS_COLUMNS,
    ENGAGEMENT_COLUMNS,
    SOUNDLINK_BREAKDOWN_COLUMNS,
    SOUNDLINK_ENGAGEMENT_COLUMNS,
    SOUNDLINKS_COLUMNS,
    as_tuple,
    breakdown_record,
    campaign_record,
    engagement_record,
    soundlink_breakdown_record,
    soundlink_engagement_record,
    soundlink_record,
)

_CAMPAIGNS_DDL = """
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id VARCHAR PRIMARY KEY,
    organization_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    social_platform VARCHAR NOT NULL,
    daily_budget DOUBLE NOT NULL,
    total_budget DOUBLE NOT NULL,
    campaign_duration INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    strategy_type VARCHAR,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL
)
"""

_BREAKDOWN_DDL = """
CREATE TABLE IF NOT EXISTS campaign_country_daily (
    provider VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    campaign_id VARCHAR NOT NULL,
    country_code VARCHAR NOT NULL,
    schema_version VARCHAR,
    report_date_timezone VARCHAR,
    exported_at TIMESTAMP,
    campaign_name VARCHAR,
    campaign_target_type VARCHAR,
    campaign_target_isrc VARCHAR,
    campaign_target_spotify_track_id VARCHAR,
    campaign_target_playlist_id VARCHAR,
    impressions BIGINT,
    ad_clicks BIGINT,
    link_clicks BIGINT,
    streams BIGINT,
    listeners BIGINT,
    followers BIGINT,
    streams_per_listener DOUBLE,
    spend_media DOUBLE,
    spend_total DOUBLE,
    fees DOUBLE,
    currency VARCHAR,
    currency_account VARCHAR,
    cpl DOUBLE,
    cpf DOUBLE,
    cpc_linkclick DOUBLE,
    ctr_linkclick DOUBLE,
    ctr_adclick DOUBLE,
    cost_per_result DOUBLE,
    result_type VARCHAR,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL,
    PRIMARY KEY (provider, account_id, report_date, campaign_id, country_code)
)
"""

_ENGAGEMENT_DDL = """
CREATE TABLE IF NOT EXISTS campaign_engagement_daily (
    provider VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    campaign_id VARCHAR NOT NULL,
    engagement_context VARCHAR NOT NULL,
    country_code VARCHAR NOT NULL,
    engaged_spotify_track_id VARCHAR NOT NULL,
    schema_version VARCHAR,
    report_date_timezone VARCHAR,
    exported_at TIMESTAMP,
    campaign_name VARCHAR,
    campaign_target_type VARCHAR,
    campaign_target_isrc VARCHAR,
    campaign_target_spotify_track_id VARCHAR,
    campaign_target_playlist_id VARCHAR,
    status VARCHAR,
    engaged_track_isrc VARCHAR,
    engaged_track_name VARCHAR,
    playlist_position INTEGER,
    new_listeners BIGINT,
    returning_listeners BIGINT,
    listeners BIGINT,
    new_listener_streams BIGINT,
    returning_listener_streams BIGINT,
    streams BIGINT,
    spl DOUBLE,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL,
    PRIMARY KEY (
        provider,
        account_id,
        report_date,
        campaign_id,
        engagement_context,
        country_code,
        engaged_spotify_track_id
    )
)
"""

_SOUNDLINKS_DDL = """
CREATE TABLE IF NOT EXISTS soundlinks (
    soundlink_id VARCHAR PRIMARY KEY,
    organization_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    url VARCHAR NOT NULL,
    target_type VARCHAR,
    spotify_url VARCHAR,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL
)
"""

_SOUNDLINK_BREAKDOWN_DDL = """
CREATE TABLE IF NOT EXISTS soundlink_country_daily (
    provider VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    soundlink_id VARCHAR NOT NULL,
    country_code VARCHAR NOT NULL,
    schema_version VARCHAR,
    report_date_timezone VARCHAR,
    exported_at TIMESTAMP,
    soundlink_name VARCHAR,
    soundlink_target_type VARCHAR,
    soundlink_target_isrc VARCHAR,
    soundlink_target_spotify_track_id VARCHAR,
    soundlink_target_playlist_id VARCHAR,
    views BIGINT,
    link_clicks BIGINT,
    streams BIGINT,
    listeners BIGINT,
    new_listeners BIGINT,
    returning_listeners BIGINT,
    new_listener_streams BIGINT,
    returning_listener_streams BIGINT,
    followers BIGINT,
    streams_per_listener DOUBLE,
    ctr_lp DOUBLE,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL,
    PRIMARY KEY (provider, account_id, report_date, soundlink_id, country_code)
)
"""

_SOUNDLINK_ENGAGEMENT_DDL = """
CREATE TABLE IF NOT EXISTS soundlink_engagement_daily (
    provider VARCHAR NOT NULL,
    account_id VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    soundlink_id VARCHAR NOT NULL,
    engagement_context VARCHAR NOT NULL,
    country_code VARCHAR NOT NULL,
    engaged_spotify_track_id VARCHAR NOT NULL,
    schema_version VARCHAR,
    report_date_timezone VARCHAR,
    exported_at TIMESTAMP,
    soundlink_name VARCHAR,
    soundlink_target_type VARCHAR,
    soundlink_target_isrc VARCHAR,
    soundlink_target_spotify_track_id VARCHAR,
    soundlink_target_playlist_id VARCHAR,
    engaged_track_isrc VARCHAR,
    engaged_track_name VARCHAR,
    playlist_position INTEGER,
    new_listeners BIGINT,
    returning_listeners BIGINT,
    listeners BIGINT,
    new_listener_streams BIGINT,
    returning_listener_streams BIGINT,
    streams BIGINT,
    spl DOUBLE,
    raw_json JSON NOT NULL,
    synced_at TIMESTAMP NOT NULL,
    PRIMARY KEY (
        provider,
        account_id,
        report_date,
        soundlink_id,
        engagement_context,
        country_code,
        engaged_spotify_track_id
    )
)
"""

# Columns added after the first MVP schema; safe on existing DuckDB files.
_BREAKDOWN_MIGRATIONS: list[tuple[str, str]] = [
    ("schema_version", "VARCHAR"),
    ("report_date_timezone", "VARCHAR"),
    ("exported_at", "TIMESTAMP"),
    ("campaign_target_type", "VARCHAR"),
    ("campaign_target_isrc", "VARCHAR"),
    ("campaign_target_spotify_track_id", "VARCHAR"),
    ("campaign_target_playlist_id", "VARCHAR"),
    ("streams_per_listener", "DOUBLE"),
    ("currency_account", "VARCHAR"),
    ("cpl", "DOUBLE"),
    ("cpf", "DOUBLE"),
    ("cpc_linkclick", "DOUBLE"),
    ("ctr_linkclick", "DOUBLE"),
    ("ctr_adclick", "DOUBLE"),
    ("cost_per_result", "DOUBLE"),
    ("result_type", "VARCHAR"),
]

_ENGAGEMENT_MIGRATIONS: list[tuple[str, str]] = [
    ("schema_version", "VARCHAR"),
    ("report_date_timezone", "VARCHAR"),
    ("exported_at", "TIMESTAMP"),
    ("campaign_target_type", "VARCHAR"),
    ("campaign_target_isrc", "VARCHAR"),
    ("campaign_target_spotify_track_id", "VARCHAR"),
    ("campaign_target_playlist_id", "VARCHAR"),
    ("engaged_track_isrc", "VARCHAR"),
    ("playlist_position", "INTEGER"),
    ("new_listener_streams", "BIGINT"),
    ("returning_listener_streams", "BIGINT"),
    ("spl", "DOUBLE"),
]


class DuckDbLoader(WarehouseLoader):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))

    def ensure_schema(self) -> None:
        self._conn.execute(_CAMPAIGNS_DDL)
        self._conn.execute(_BREAKDOWN_DDL)
        self._conn.execute(_ENGAGEMENT_DDL)
        self._conn.execute(_SOUNDLINKS_DDL)
        self._conn.execute(_SOUNDLINK_BREAKDOWN_DDL)
        self._conn.execute(_SOUNDLINK_ENGAGEMENT_DDL)
        self._migrate("campaign_country_daily", _BREAKDOWN_MIGRATIONS)
        self._migrate("campaign_engagement_daily", _ENGAGEMENT_MIGRATIONS)

    def _migrate(self, table: str, columns: list[tuple[str, str]]) -> None:
        for name, sql_type in columns:
            self._conn.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {sql_type}"
            )

    def _transaction(self, fn: Callable[[], None]) -> None:
        self._conn.execute("BEGIN TRANSACTION")
        try:
            fn()
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def upsert_campaigns(self, campaigns: list[CampaignSummary]) -> int:
        if not campaigns:
            return 0
        synced_at = datetime.now(tz=UTC)
        rows = [
            as_tuple(campaign_record(c, synced_at), CAMPAIGNS_COLUMNS) for c in campaigns
        ]
        placeholders = ", ".join("?" for _ in CAMPAIGNS_COLUMNS)
        cols = ", ".join(CAMPAIGNS_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO campaigns ({cols}) VALUES ({placeholders})",
                rows,
            )

        self._transaction(_write)
        return len(rows)

    def upsert_breakdown_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        values = [
            as_tuple(breakdown_record(row, synced_at), BREAKDOWN_COLUMNS) for row in rows
        ]
        placeholders = ", ".join("?" for _ in BREAKDOWN_COLUMNS)
        cols = ", ".join(BREAKDOWN_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO campaign_country_daily ({cols}) "
                f"VALUES ({placeholders})",
                values,
            )

        self._transaction(_write)
        return len(values)

    def upsert_engagement_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        values = [
            as_tuple(engagement_record(row, synced_at), ENGAGEMENT_COLUMNS)
            for row in rows
        ]
        placeholders = ", ".join("?" for _ in ENGAGEMENT_COLUMNS)
        cols = ", ".join(ENGAGEMENT_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO campaign_engagement_daily ({cols}) "
                f"VALUES ({placeholders})",
                values,
            )

        self._transaction(_write)
        return len(values)

    def upsert_soundlinks(self, soundlinks: list[SoundlinkSummary]) -> int:
        if not soundlinks:
            return 0
        synced_at = datetime.now(tz=UTC)
        rows = [
            as_tuple(soundlink_record(s, synced_at), SOUNDLINKS_COLUMNS)
            for s in soundlinks
        ]
        placeholders = ", ".join("?" for _ in SOUNDLINKS_COLUMNS)
        cols = ", ".join(SOUNDLINKS_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO soundlinks ({cols}) VALUES ({placeholders})",
                rows,
            )

        self._transaction(_write)
        return len(rows)

    def upsert_soundlink_breakdown_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        values = [
            as_tuple(soundlink_breakdown_record(row, synced_at), SOUNDLINK_BREAKDOWN_COLUMNS)
            for row in rows
        ]
        placeholders = ", ".join("?" for _ in SOUNDLINK_BREAKDOWN_COLUMNS)
        cols = ", ".join(SOUNDLINK_BREAKDOWN_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO soundlink_country_daily ({cols}) "
                f"VALUES ({placeholders})",
                values,
            )

        self._transaction(_write)
        return len(values)

    def upsert_soundlink_engagement_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        values = [
            as_tuple(
                soundlink_engagement_record(row, synced_at), SOUNDLINK_ENGAGEMENT_COLUMNS
            )
            for row in rows
        ]
        placeholders = ", ".join("?" for _ in SOUNDLINK_ENGAGEMENT_COLUMNS)
        cols = ", ".join(SOUNDLINK_ENGAGEMENT_COLUMNS)

        def _write() -> None:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO soundlink_engagement_daily ({cols}) "
                f"VALUES ({placeholders})",
                values,
            )

        self._transaction(_write)
        return len(values)

    def close(self) -> None:
        self._conn.close()
