# GitHub Actions (scheduled sync)

Run `soundlink-sync` on a cron schedule from GitHub Actions. Prefer **BigQuery**
as the destination — a DuckDB file on the runner is ephemeral unless you upload
it elsewhere each run.

## Prerequisites

1. This repo checked out in the Actions workspace (`actions/checkout` below).
2. Repo secrets (Settings → Secrets and variables → Actions):

| Secret                 | Notes                                                                |
| ---------------------- | -------------------------------------------------------------------- |
| `SOUNDLINK_API_KEY`    | Org API key (`campaigns:read`, `metrics:read`)                       |
| `BIGQUERY_PROJECT`     | GCP project id                                                       |
| `BIGQUERY_DATASET`     | Dataset id (created on first sync if missing)                        |
| `GCP_CREDENTIALS_JSON` | Service account JSON with `bigquery.dataEditor` + `bigquery.jobUser` |

2. Optional: pin `BIGQUERY_LOCATION` (default in the connector is `US`).

For production GCP, prefer [Workload Identity Federation](https://github.com/google-github-actions/auth#workload-identity-federation-through-a-service-account)
instead of a long-lived JSON key. The example below uses a JSON key for
simplicity.

## Workflow

Copy to `.github/workflows/soundlink-sync.yml` (or merge into an existing workflow):

```yaml
name: Soundlink warehouse sync

on:
  schedule:
    # 06:00 UTC daily — adjust to your timezone / reporting needs
    - cron: "0 6 * * *"
  workflow_dispatch: {}

permissions:
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install
        run: uv sync --extra bigquery

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_CREDENTIALS_JSON }}

      - name: Sync (incremental)
        env:
          SOUNDLINK_API_KEY: ${{ secrets.SOUNDLINK_API_KEY }}
          DESTINATION: bigquery
          BIGQUERY_PROJECT: ${{ secrets.BIGQUERY_PROJECT }}
          BIGQUERY_DATASET: ${{ secrets.BIGQUERY_DATASET }}
          BIGQUERY_LOCATION: US
          # Ephemeral on the runner; resume within a single job only
          STATE_PATH: ./data/sync_state.json
        run: |
          uv run soundlink-sync ping
          uv run soundlink-sync sync --mode incremental
```

## First-time backfill

Before relying on the schedule, run a full sync once (Actions → workflow →
**Run workflow**, or locally):

```bash
uv run soundlink-sync sync --mode full
# or per campaign:
uv run soundlink-sync sync --mode full --campaign-id <uuid>
```

Then leave the daily job on `--mode incremental`.

## Notes

- **Idempotent**: re-runs upsert / `MERGE` on Public API primary keys.
- **Resume**: `STATE_PATH` on the runner does not survive across jobs. If a run
  fails mid-org, the next scheduled run re-fetches all campaigns for that day
  (safe, but more API load). Persist state to GCS/Artifact only if you need
  cross-run resume.
- **Rate limits**: the connector honors `Retry-After` on 429; keep
  `CAMPAIGNS_PAGE_SIZE` at the default (`25`) unless you know the org is small.
- **Secrets**: never commit `.env` or service-account JSON.
