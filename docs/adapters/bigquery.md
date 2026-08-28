# BigQuery adapter

Cloud warehouse destination. Loads rows into a staging table, then **MERGE**s
into target tables on the same primary keys as the Public API / DuckDB adapter.

## When to use

- Labels / agencies with an existing GCP data warehouse
- Scheduled syncs (Cloud Run Job, Composer, cron on a VM with ADC)
- Joining Soundlink metrics with royalties, CRM, or other BigQuery sources

## Prerequisites

1. Install the optional dependency: `uv sync --extra bigquery`
2. GCP project with BigQuery API enabled
3. Credentials via [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials):
   - Local: `gcloud auth application-default login`
   - Prod: service account + `GOOGLE_APPLICATION_CREDENTIALS`, or workload identity
4. IAM on the dataset (or project): `bigquery.dataEditor`, `bigquery.jobUser`

## Configuration

| Variable            | Required | Notes                           |
| ------------------- | -------- | ------------------------------- |
| `DESTINATION`       | yes      | `bigquery`                      |
| `BIGQUERY_PROJECT`  | yes      | GCP project id                  |
| `BIGQUERY_DATASET`  | yes      | Dataset id (created if missing) |
| `BIGQUERY_LOCATION` | no       | Default `US`                    |

```env
DESTINATION=bigquery
BIGQUERY_PROJECT=my-gcp-project
BIGQUERY_DATASET=soundlink
BIGQUERY_LOCATION=US
SOUNDLINK_API_KEY=sk_...
```

## Behavior

| Step        | Detail                                                             |
| ----------- | ------------------------------------------------------------------ |
| Dataset     | Created if missing (`exists_ok`)                                   |
| Tables      | `campaigns`, `campaign_country_daily`, `campaign_engagement_daily` |
| Schema      | Existing tables: missing columns are **added** (nullable)          |
| Upsert      | Load NDJSON → temp staging table → `MERGE` on PK → drop staging    |
| Staging TTL | Table expiration ~1 day (cleanup safety net)                       |

Primary keys match the Public API docs (`campaign_country_daily` / `campaign_engagement_daily` v1.0).

## Sync

```bash
uv run soundlink-sync ping
uv run soundlink-sync sync --mode incremental
uv run soundlink-sync sync --mode full --campaign-id <uuid>
```

## Query

```sql
SELECT campaign_id, country_code, report_date, streams, spend_total, cpl
FROM `my-gcp-project.soundlink.campaign_country_daily`
ORDER BY report_date DESC
LIMIT 10;
```

```sql
SELECT c.campaign_id, c.status,
       SUM(m.spend_total) AS spend,
       SUM(m.streams) AS streams
FROM `my-gcp-project.soundlink.campaigns` c
JOIN `my-gcp-project.soundlink.campaign_country_daily` m
  USING (campaign_id)
WHERE m.report_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY spend DESC;
```

## Notes

- First `ensure_schema` may create empty tables; costs are negligible until data lands.
- Large orgs: prefer incremental daily sync; use `--mode full` once per campaign for backfill.
- Rate limits are on the **Soundlink API** side; BigQuery load/MERGE is per batch.
