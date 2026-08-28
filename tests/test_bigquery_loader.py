from __future__ import annotations

from unittest.mock import MagicMock

from soundlink_warehouse_connector.loaders.bigquery import BigQueryLoader
from soundlink_warehouse_connector.loaders.bigquery_schema import (
    BREAKDOWN_PK,
    BREAKDOWN_SCHEMA,
    CAMPAIGNS_PK,
    CAMPAIGNS_SCHEMA,
    merge_sql,
)


def test_merge_sql_campaigns_contains_pk_and_update() -> None:
    sql = merge_sql(
        target="proj.ds.campaigns",
        staging="proj.ds._staging_campaigns",
        schema=CAMPAIGNS_SCHEMA,
        pk=CAMPAIGNS_PK,
    )
    assert "MERGE `proj.ds.campaigns` T" in sql
    assert "USING `proj.ds._staging_campaigns` S" in sql
    assert "T.`campaign_id` = S.`campaign_id`" in sql
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "T.`status` = S.`status`" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql


def test_merge_sql_breakdown_pk() -> None:
    sql = merge_sql(
        target="p.d.campaign_country_daily",
        staging="p.d.stg",
        schema=BREAKDOWN_SCHEMA,
        pk=BREAKDOWN_PK,
    )
    for col in BREAKDOWN_PK:
        assert f"T.`{col}` = S.`{col}`" in sql
    assert "T.`cpl` = S.`cpl`" in sql


def test_upsert_breakdown_empty_short_circuits() -> None:
    client = MagicMock()
    loader = BigQueryLoader(
        project="p",
        dataset="d",
        client=client,
    )
    assert loader.upsert_breakdown_rows([]) == 0
    client.load_table_from_json.assert_not_called()


def test_upsert_breakdown_passes_raw_json_as_object() -> None:
    client = MagicMock()
    load_job = MagicMock()
    client.load_table_from_json.return_value = load_job
    client.query.return_value = MagicMock()

    loader = BigQueryLoader(project="p", dataset="d", client=client)
    row = {
        "provider": "soundlink",
        "account_id": "acct-1",
        "report_date": "2026-04-01",
        "campaign_id": "camp-1",
        "country_code": "US",
        "streams": 10,
    }
    assert loader.upsert_breakdown_rows([row]) == 1

    loaded_rows = client.load_table_from_json.call_args[0][0]
    assert isinstance(loaded_rows[0]["raw_json"], dict)
    assert loaded_rows[0]["raw_json"]["campaign_id"] == "camp-1"
    assert loaded_rows[0]["raw_json"]["streams"] == 10



def test_ensure_table_adds_missing_columns_as_nullable() -> None:
    from google.cloud import bigquery

    client = MagicMock()
    existing = MagicMock()
    existing.schema = [
        bigquery.SchemaField("provider", "STRING"),
        bigquery.SchemaField("account_id", "STRING"),
    ]
    client.get_table.return_value = existing

    loader = BigQueryLoader(project="p", dataset="d", client=client)
    loader._ensure_table("campaign_country_daily", BREAKDOWN_SCHEMA)

    client.update_table.assert_called_once()
    updated_table, fields = client.update_table.call_args[0]
    assert fields == ["schema"]
    added = {f.name: f for f in updated_table.schema if f.name not in {"provider", "account_id"}}
    assert "cpl" in added
    assert "report_date" in added
    assert "raw_json" in added
    # BigQuery rejects ADD COLUMN with REQUIRED — migrations must be NULLABLE.
    assert all(f.mode == "NULLABLE" for f in added.values())


def test_ensure_table_creates_when_missing() -> None:
    from google.api_core.exceptions import NotFound

    client = MagicMock()
    client.get_table.side_effect = NotFound("missing")
    loader = BigQueryLoader(project="p", dataset="d", client=client)
    loader._ensure_table("campaigns", CAMPAIGNS_SCHEMA)
    client.create_table.assert_called_once()
    client.update_table.assert_not_called()
