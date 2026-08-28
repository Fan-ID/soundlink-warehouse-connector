from __future__ import annotations

from google.cloud import bigquery

from soundlink_warehouse_connector.loaders.columns import (
    BREAKDOWN_PK,
    CAMPAIGNS_PK,
    ENGAGEMENT_PK,
)

__all__ = [
    "BREAKDOWN_PK",
    "BREAKDOWN_SCHEMA",
    "CAMPAIGNS_PK",
    "CAMPAIGNS_SCHEMA",
    "ENGAGEMENT_PK",
    "ENGAGEMENT_SCHEMA",
    "merge_sql",
]

CAMPAIGNS_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("organization_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("social_platform", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("daily_budget", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("total_budget", "FLOAT64", mode="REQUIRED"),
    bigquery.SchemaField("campaign_duration", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("generation", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("strategy_type", "STRING"),
    bigquery.SchemaField("raw_json", "JSON", mode="REQUIRED"),
    bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED"),
]

BREAKDOWN_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("provider", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("report_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("country_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("schema_version", "STRING"),
    bigquery.SchemaField("report_date_timezone", "STRING"),
    bigquery.SchemaField("exported_at", "TIMESTAMP"),
    bigquery.SchemaField("campaign_name", "STRING"),
    bigquery.SchemaField("campaign_target_type", "STRING"),
    bigquery.SchemaField("campaign_target_isrc", "STRING"),
    bigquery.SchemaField("campaign_target_spotify_track_id", "STRING"),
    bigquery.SchemaField("campaign_target_playlist_id", "STRING"),
    bigquery.SchemaField("impressions", "INT64"),
    bigquery.SchemaField("ad_clicks", "INT64"),
    bigquery.SchemaField("link_clicks", "INT64"),
    bigquery.SchemaField("streams", "INT64"),
    bigquery.SchemaField("listeners", "INT64"),
    bigquery.SchemaField("followers", "INT64"),
    bigquery.SchemaField("streams_per_listener", "FLOAT64"),
    bigquery.SchemaField("spend_media", "FLOAT64"),
    bigquery.SchemaField("spend_total", "FLOAT64"),
    bigquery.SchemaField("fees", "FLOAT64"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("currency_account", "STRING"),
    bigquery.SchemaField("cpl", "FLOAT64"),
    bigquery.SchemaField("cpf", "FLOAT64"),
    bigquery.SchemaField("cpc_linkclick", "FLOAT64"),
    bigquery.SchemaField("ctr_linkclick", "FLOAT64"),
    bigquery.SchemaField("ctr_adclick", "FLOAT64"),
    bigquery.SchemaField("cost_per_result", "FLOAT64"),
    bigquery.SchemaField("result_type", "STRING"),
    bigquery.SchemaField("raw_json", "JSON", mode="REQUIRED"),
    bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED"),
]

ENGAGEMENT_SCHEMA: list[bigquery.SchemaField] = [
    bigquery.SchemaField("provider", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("report_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("engagement_context", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("country_code", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("engaged_spotify_track_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("schema_version", "STRING"),
    bigquery.SchemaField("report_date_timezone", "STRING"),
    bigquery.SchemaField("exported_at", "TIMESTAMP"),
    bigquery.SchemaField("campaign_name", "STRING"),
    bigquery.SchemaField("campaign_target_type", "STRING"),
    bigquery.SchemaField("campaign_target_isrc", "STRING"),
    bigquery.SchemaField("campaign_target_spotify_track_id", "STRING"),
    bigquery.SchemaField("campaign_target_playlist_id", "STRING"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("engaged_track_isrc", "STRING"),
    bigquery.SchemaField("engaged_track_name", "STRING"),
    bigquery.SchemaField("playlist_position", "INT64"),
    bigquery.SchemaField("new_listeners", "INT64"),
    bigquery.SchemaField("returning_listeners", "INT64"),
    bigquery.SchemaField("listeners", "INT64"),
    bigquery.SchemaField("new_listener_streams", "INT64"),
    bigquery.SchemaField("returning_listener_streams", "INT64"),
    bigquery.SchemaField("streams", "INT64"),
    bigquery.SchemaField("spl", "FLOAT64"),
    bigquery.SchemaField("raw_json", "JSON", mode="REQUIRED"),
    bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED"),
]


def merge_sql(
    *,
    target: str,
    staging: str,
    schema: list[bigquery.SchemaField],
    pk: tuple[str, ...],
) -> str:
    columns = [f.name for f in schema]
    on_clause = " AND ".join(f"T.`{c}` = S.`{c}`" for c in pk)
    update_cols = [c for c in columns if c not in pk]
    set_clause = ", ".join(f"T.`{c}` = S.`{c}`" for c in update_cols)
    insert_cols = ", ".join(f"`{c}`" for c in columns)
    insert_vals = ", ".join(f"S.`{c}`" for c in columns)
    return f"""
MERGE `{target}` T
USING `{staging}` S
ON {on_clause}
WHEN MATCHED THEN UPDATE SET {set_clause}
WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
""".strip()
