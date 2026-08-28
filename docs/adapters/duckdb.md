# DuckDB adapter

Local warehouse destination for development and demos. Writes to a single file
(default `./data/soundlink.duckdb`). No cloud account required.

## When to use

- Local validation of the connector
- CI / demos without GCP credentials
- Small orgs that query with DuckDB CLI / Python

## Configuration

| Variable      | Default                   | Notes                 |
| ------------- | ------------------------- | --------------------- |
| `DESTINATION` | `duckdb`                  |                       |
| `DUCKDB_PATH` | `./data/soundlink.duckdb` | Created on first sync |

```env
DESTINATION=duckdb
DUCKDB_PATH=./data/soundlink.duckdb
```

## Behavior

- Tables: `campaigns`, `campaign_country_daily`, `campaign_engagement_daily`
- Upsert: `INSERT OR REPLACE` on Public API primary keys (each batch in a transaction)
- Schema migrations: `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for new fields

## Query

```bash
uv run python <<'PY'
import duckdb
c = duckdb.connect("data/soundlink.duckdb", read_only=True)
print(c.execute("""
  SELECT campaign_id, country_code, report_date, streams, spend_total, cpl
  FROM campaign_country_daily
  ORDER BY report_date DESC
  LIMIT 10
""").fetchall())
PY
```

```sql
SELECT c.campaign_id, c.status,
       SUM(m.spend_total) AS spend,
       SUM(m.streams) AS streams
FROM campaigns c
JOIN campaign_country_daily m USING (campaign_id)
WHERE m.report_date >= current_date - INTERVAL 30 DAY
GROUP BY 1, 2
ORDER BY spend DESC;
```
