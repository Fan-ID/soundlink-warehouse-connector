from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from soundlink_warehouse_connector.client.models import CampaignSummary, SoundlinkSummary
from soundlink_warehouse_connector.loaders.base import WarehouseLoader
from soundlink_warehouse_connector.loaders.bigquery_schema import (
    BREAKDOWN_PK,
    BREAKDOWN_SCHEMA,
    CAMPAIGNS_PK,
    CAMPAIGNS_SCHEMA,
    ENGAGEMENT_PK,
    ENGAGEMENT_SCHEMA,
    SOUNDLINK_BREAKDOWN_PK,
    SOUNDLINK_BREAKDOWN_SCHEMA,
    SOUNDLINK_ENGAGEMENT_PK,
    SOUNDLINK_ENGAGEMENT_SCHEMA,
    SOUNDLINKS_PK,
    SOUNDLINKS_SCHEMA,
    merge_sql,
)
from soundlink_warehouse_connector.loaders.columns import (
    breakdown_record,
    campaign_record,
    engagement_record,
    json_safe,
    soundlink_breakdown_record,
    soundlink_engagement_record,
    soundlink_record,
)

logger = logging.getLogger(__name__)


def _as_nullable(field: bigquery.SchemaField) -> bigquery.SchemaField:
    """BigQuery only allows adding NULLABLE columns to existing tables."""
    return bigquery.SchemaField(
        field.name,
        field.field_type,
        mode="NULLABLE",
        description=field.description,
        fields=field.fields,
    )


class BigQueryLoader(WarehouseLoader):
    def __init__(
        self,
        *,
        project: str,
        dataset: str,
        location: str = "US",
        client: bigquery.Client | None = None,
    ) -> None:
        self._project = project
        self._dataset = dataset
        self._location = location
        self._client = client or bigquery.Client(project=project, location=location)
        self._dataset_ref = f"{project}.{dataset}"

    def close(self) -> None:
        self._client.close()

    def ensure_schema(self) -> None:
        dataset = bigquery.Dataset(self._dataset_ref)
        dataset.location = self._location
        try:
            self._client.get_dataset(self._dataset_ref)
        except NotFound:
            self._client.create_dataset(dataset)
            logger.info("Created BigQuery dataset %s", self._dataset_ref)

        self._ensure_table("campaigns", CAMPAIGNS_SCHEMA)
        self._ensure_table("campaign_country_daily", BREAKDOWN_SCHEMA)
        self._ensure_table("campaign_engagement_daily", ENGAGEMENT_SCHEMA)
        self._ensure_table("soundlinks", SOUNDLINKS_SCHEMA)
        self._ensure_table("soundlink_country_daily", SOUNDLINK_BREAKDOWN_SCHEMA)
        self._ensure_table("soundlink_engagement_daily", SOUNDLINK_ENGAGEMENT_SCHEMA)

    def _table_id(self, name: str) -> str:
        return f"{self._dataset_ref}.{name}"

    def _ensure_table(self, name: str, schema: list[bigquery.SchemaField]) -> None:
        table_id = self._table_id(name)
        try:
            existing = self._client.get_table(table_id)
        except NotFound:
            table = bigquery.Table(table_id, schema=schema)
            self._client.create_table(table)
            logger.info("Created BigQuery table %s", table_id)
            return

        existing_names = {field.name for field in existing.schema}
        missing = [
            _as_nullable(field) for field in schema if field.name not in existing_names
        ]
        if not missing:
            return

        existing.schema = list(existing.schema) + missing
        self._client.update_table(existing, ["schema"])
        logger.info(
            "Migrated BigQuery table %s: added %s",
            table_id,
            ", ".join(field.name for field in missing),
        )

    def upsert_campaigns(self, campaigns: list[CampaignSummary]) -> int:
        if not campaigns:
            return 0
        synced_at = datetime.now(tz=UTC)
        rows = [campaign_record(c, synced_at) for c in campaigns]
        return self._merge_rows("campaigns", CAMPAIGNS_SCHEMA, CAMPAIGNS_PK, rows)

    def upsert_breakdown_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        prepared = [breakdown_record(row, synced_at) for row in rows]
        return self._merge_rows(
            "campaign_country_daily", BREAKDOWN_SCHEMA, BREAKDOWN_PK, prepared
        )

    def upsert_engagement_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        prepared = [engagement_record(row, synced_at) for row in rows]
        return self._merge_rows(
            "campaign_engagement_daily", ENGAGEMENT_SCHEMA, ENGAGEMENT_PK, prepared
        )

    def upsert_soundlinks(self, soundlinks: list[SoundlinkSummary]) -> int:
        if not soundlinks:
            return 0
        synced_at = datetime.now(tz=UTC)
        rows = [soundlink_record(s, synced_at) for s in soundlinks]
        return self._merge_rows("soundlinks", SOUNDLINKS_SCHEMA, SOUNDLINKS_PK, rows)

    def upsert_soundlink_breakdown_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        prepared = [soundlink_breakdown_record(row, synced_at) for row in rows]
        return self._merge_rows(
            "soundlink_country_daily",
            SOUNDLINK_BREAKDOWN_SCHEMA,
            SOUNDLINK_BREAKDOWN_PK,
            prepared,
        )

    def upsert_soundlink_engagement_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        synced_at = datetime.now(tz=UTC)
        prepared = [soundlink_engagement_record(row, synced_at) for row in rows]
        return self._merge_rows(
            "soundlink_engagement_daily",
            SOUNDLINK_ENGAGEMENT_SCHEMA,
            SOUNDLINK_ENGAGEMENT_PK,
            prepared,
        )

    def _merge_rows(
        self,
        table_name: str,
        schema: list[bigquery.SchemaField],
        pk: tuple[str, ...],
        rows: list[dict[str, Any]],
    ) -> int:
        staging_name = f"_staging_{table_name}_{uuid4().hex[:8]}"
        staging_id = self._table_id(staging_name)
        target_id = self._table_id(table_name)

        staging = bigquery.Table(staging_id, schema=schema)
        staging.expires = datetime.now(tz=UTC) + timedelta(days=1)
        self._client.create_table(staging)

        try:
            job_config = bigquery.LoadJobConfig(
                schema=schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            )
            load_job = self._client.load_table_from_json(
                [{k: json_safe(v) for k, v in row.items()} for row in rows],
                staging_id,
                job_config=job_config,
            )
            load_job.result()

            sql = merge_sql(
                target=target_id,
                staging=staging_id,
                schema=schema,
                pk=pk,
            )
            self._client.query(sql).result()
        finally:
            self._client.delete_table(staging_id, not_found_ok=True)

        logger.info("Merged %s rows into %s", len(rows), target_id)
        return len(rows)
