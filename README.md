# Soundlink Warehouse Connector

ELT connector: **Soundlink Public API → warehouse** (DuckDB or BigQuery).

[getsoundlink.com/docs](https://getsoundlink.com/docs) — API key auth, campaign list, and JSONL metric exports.

```text
api.getsoundlink.com  →  soundlink-sync  →  DuckDB | BigQuery
```

## Requirements

- Python **3.13+** (developed on 3.14)
- [uv](https://docs.astral.sh/uv/) ([install](https://docs.astral.sh/uv/getting-started/installation/))
- Soundlink org API key with `campaigns:read` and `metrics:read`  
  (Soundlink app → Settings → Developer → API keys)

## Setup

This package is **not on PyPI yet**. Install from the GitHub repo (editable / local).

```bash
# 1. Clone
git clone https://github.com/Fan-ID/soundlink-warehouse-connector.git
cd soundlink-warehouse-connector

# 2. Create the virtualenv and install the package + deps (uv reads pyproject.toml)
uv sync

# 3. BigQuery destination also needs the optional extra:
# uv sync --extra bigquery

# 4. Environment file
cp .env.example .env
# Edit .env and set at least:
#   SOUNDLINK_API_KEY=sk_...
# Optional: DESTINATION, DUCKDB_PATH, STATE_PATH, lookback, etc.
```

`uv sync` installs the project in editable mode, so `uv run soundlink-sync …` works
without a separate `pip install`.

If you already have the repo checked out elsewhere (monorepo checkout, zip, etc.):

```bash
cd /path/to/soundlink-warehouse-connector
uv sync
cp .env.example .env
```

Verify credentials:

```bash
uv run soundlink-sync ping
# → OK: {'status': 'ok', 'organizationId': '...'}
```

### Destinations

| Adapter              | Doc                                                    | When                             |
| -------------------- | ------------------------------------------------------ | -------------------------------- |
| **DuckDB** (default) | [docs/adapters/duckdb.md](docs/adapters/duckdb.md)     | Local / MVP                      |
| **BigQuery**         | [docs/adapters/bigquery.md](docs/adapters/bigquery.md) | Cloud warehouse + scheduled jobs |

DuckDB needs no extra install. BigQuery needs `uv sync --extra bigquery` and
[Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
(`gcloud auth application-default login` locally, or a service account in CI).

## Quick start (DuckDB)

```bash
uv run soundlink-sync ping
uv run soundlink-sync sync --mode incremental
```

Data lands in `./data/soundlink.duckdb` by default. State/resume file:
`./data/sync_state.json`.

## Configuration

Shared env (all destinations) — see `.env.example` for the full template:

| Variable                    | Default                        | Notes                                                  |
| --------------------------- | ------------------------------ | ------------------------------------------------------ |
| `SOUNDLINK_API_KEY`         | —                              | Required                                               |
| `SOUNDLINK_BASE_URL`        | `https://api.getsoundlink.com` |                                                        |
| `DESTINATION`               | `duckdb`                       | `duckdb` \| `bigquery`                                 |
| `DUCKDB_PATH`               | `./data/soundlink.duckdb`      | When `DESTINATION=duckdb`                              |
| `STATE_PATH`                | `./data/sync_state.json`       | Resume + last successful sync                          |
| `INCREMENTAL_LOOKBACK_DAYS` | `10`                           | Inclusive days ending today (covers ~7-day mutability) |
| `CAMPAIGNS_PAGE_SIZE`       | `25`                           | Max 100                                                |
| `REQUEST_TIMEOUT_SECONDS`   | `120`                          |                                                        |
| `MAX_RETRIES`               | `5`                            | Honors `Retry-After` on 429                            |
| `BIGQUERY_PROJECT`          | —                              | Required if `DESTINATION=bigquery`                     |
| `BIGQUERY_DATASET`          | —                              | Required if `DESTINATION=bigquery`                     |
| `BIGQUERY_LOCATION`         | `US`                           |                                                        |

## CLI

```bash
uv run soundlink-sync ping
uv run soundlink-sync sync --mode incremental
uv run soundlink-sync sync --mode full
uv run soundlink-sync sync --mode incremental --campaign-id <uuid>
uv run soundlink-sync sync --mode incremental --no-resume
```

| Mode          | Behavior                                                          |
| ------------- | ----------------------------------------------------------------- |
| `incremental` | Last N inclusive days, clamped to `createdAt`; skip if no overlap |
| `full`        | Backfill from `createdAt` → today in ≤90-day windows              |

Re-runs are **idempotent** (upsert / `MERGE` on documented primary keys).

### Resume / state

On failure mid-run (org-wide sync only), progress is saved under
`run:{mode}:{YYYY-MM-DD}` with `completed_campaign_ids`. The next org-wide sync
for the same mode + calendar day **skips** those campaigns. After a fully
successful org-wide run, `last_sync` is written and the in-progress key is cleared.

`--campaign-id` uses `GET /v1/campaigns/{id}` and **does not** read or clear
org-wide resume state (so a single-campaign sync cannot wipe a partial full-org run).

Use `--no-resume` to ignore progress and re-fetch every campaign.

`last_sync` is set **only** when the run finishes with zero errors.

## What gets synced

| Stream           | Source                        | Table                       |
| ---------------- | ----------------------------- | --------------------------- |
| Campaigns        | `GET /v1/campaigns`           | `campaigns`                 |
| Country daily    | `…/metrics/breakdown/export`  | `campaign_country_daily`    |
| Engagement daily | `…/metrics/engagement/export` | `campaign_engagement_daily` |

### Primary keys

- `campaigns`: `campaign_id`
- `campaign_country_daily`: `(provider, account_id, report_date, campaign_id, country_code)`
- `campaign_engagement_daily`: `(provider, account_id, report_date, campaign_id, engagement_context, country_code, engaged_spotify_track_id)`

### Metrics caveats (from public docs)

- Rows for a `report_date` can change for up to **7 days** — incremental lookback re-upserts that window.
- Export requests are capped at **90 days**; full sync slices automatically.
- Do **not** sum `listeners` across days on engagement rows.

## Scheduling

Run `--mode full` once (or per campaign), then keep incremental on a schedule.

| How                           | Doc                                                                    |
| ----------------------------- | ---------------------------------------------------------------------- |
| **GitHub Actions** (cron)     | [docs/scheduling/github-actions.md](docs/scheduling/github-actions.md) |
| **Cloud Run Job** + Scheduler | [docs/scheduling/cloud-run.md](docs/scheduling/cloud-run.md)           |
| Host crontab                  | see below                                                              |

```cron
0 6 * * * cd /path/to/soundlink-warehouse-connector && /path/to/uv run soundlink-sync sync --mode incremental >> /var/log/soundlink-sync.log 2>&1
```

## Development

```bash
uv sync --extra bigquery   # include BQ deps used by tests
uv run pytest
uv run ruff check src tests
```

```text
src/soundlink_warehouse_connector/
  client/      # Public API HTTP client
  sync/        # Orchestration + resume
  loaders/     # duckdb, bigquery
  state/       # Sync progress + last_sync JSON
  cli.py
docs/
  adapters/    # Per-destination setup
  scheduling/  # CI / cron examples
```

## Roadmap

- [x] DuckDB loader
- [x] BigQuery loader (`MERGE`)
- [x] GitHub Actions scheduled sync example
- [x] Cloud Run Job example
- [ ] Airbyte source connector (if partners need catalog distribution)

## License

Internal Soundlink reference connector. **Not published on PyPI** — clone and
`uv sync` as above.
