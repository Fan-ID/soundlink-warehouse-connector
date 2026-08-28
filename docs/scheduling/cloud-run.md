# Cloud Run Job (scheduled sync)

Run `soundlink-sync` as a **Cloud Run Job** on a schedule (Cloud Scheduler).
Prefer **BigQuery** as the destination — the container filesystem is ephemeral.

## Prerequisites

1. GCP project with billing, APIs enabled:
   - Cloud Run, Cloud Build (or Artifact Registry), Cloud Scheduler
   - BigQuery
2. Artifact Registry repo for the image (or use `gcr.io`)
3. Service account for the job with:
   - `roles/bigquery.dataEditor` (or dataset-scoped equivalent)
   - `roles/bigquery.jobUser`
4. Secret for the Soundlink API key (Secret Manager recommended)

## Container

Build from the repo root (see also the root `Dockerfile`):

```bash
export PROJECT_ID=my-gcp-project
export REGION=us-central1
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/soundlink/warehouse-sync:latest

gcloud artifacts repositories create soundlink \
  --repository-format=docker \
  --location=${REGION} \
  --project=${PROJECT_ID}   # once

gcloud builds submit --tag "${IMAGE}" --project="${PROJECT_ID}"
```

The image entrypoint is `soundlink-sync`. Default command: `sync --mode incremental`.

## Secrets and env

```bash
# Once: store the API key
echo -n "sk_..." | gcloud secrets create soundlink-api-key \
  --data-file=- --project="${PROJECT_ID}"

gcloud secrets add-iam-policy-binding soundlink-api-key \
  --member="serviceAccount:soundlink-sync@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}"
```

Job env (non-secret):

| Variable            | Example                |
| ------------------- | ---------------------- |
| `DESTINATION`       | `bigquery`             |
| `BIGQUERY_PROJECT`  | same as `PROJECT_ID`   |
| `BIGQUERY_DATASET`  | `soundlink`            |
| `BIGQUERY_LOCATION` | `US`                   |
| `STATE_PATH`        | `/tmp/sync_state.json` |

`SOUNDLINK_API_KEY` should come from Secret Manager, not a plain env var in the job YAML committed to git.

## Create the job

```bash
export SA=soundlink-sync@${PROJECT_ID}.iam.gserviceaccount.com

gcloud run jobs create soundlink-warehouse-sync \
  --image="${IMAGE}" \
  --region="${REGION}" \
  --service-account="${SA}" \
  --task-timeout=60m \
  --max-retries=1 \
  --set-env-vars="DESTINATION=bigquery,BIGQUERY_PROJECT=${PROJECT_ID},BIGQUERY_DATASET=soundlink,BIGQUERY_LOCATION=US,STATE_PATH=/tmp/sync_state.json" \
  --set-secrets="SOUNDLINK_API_KEY=soundlink-api-key:latest" \
  --command=soundlink-sync \
  --args=sync,--mode,incremental \
  --project="${PROJECT_ID}"
```

Manual run:

```bash
gcloud run jobs execute soundlink-warehouse-sync --region="${REGION}" --project="${PROJECT_ID}"
```

One-off full backfill (override args):

```bash
gcloud run jobs execute soundlink-warehouse-sync \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --update-args=sync,--mode,full
```

(Use the console or a temporary job update if your `gcloud` version does not support `--update-args`.)

## Schedule (Cloud Scheduler)

```bash
# Allow Scheduler to run the job
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
  --role="roles/run.invoker"   # or grant on the job only

gcloud scheduler jobs create http soundlink-warehouse-sync-daily \
  --location="${REGION}" \
  --schedule="0 6 * * *" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/soundlink-warehouse-sync:run" \
  --http-method=POST \
  --oauth-service-account-email="${SA}" \
  --project="${PROJECT_ID}"
```

Prefer the current Scheduler → Cloud Run Job integration in the Cloud Console if the URI shape changes for your API version; the important part is: **cron daily → execute the job**.

## First-time backfill

Before relying on the schedule, execute once with `--mode full` (job execute override or a local run with ADC):

```bash
uv sync --extra bigquery
export DESTINATION=bigquery BIGQUERY_PROJECT=... BIGQUERY_DATASET=...
uv run soundlink-sync sync --mode full
```

Then leave the job on incremental.

## Notes

- **Idempotent**: upsert / `MERGE` on Public API primary keys.
- **Resume**: `/tmp/sync_state.json` does not survive across job executions. Safe to re-run; more API load if a prior run failed mid-org. Mount a GCS volume or download/upload state only if you need cross-run resume.
- **Auth to BigQuery**: the job runtime SA is enough (ADC inside the container). Do not bake a JSON key into the image.
- **Secrets**: never commit `.env` or service-account JSON; `.dockerignore` excludes them from the build context.
- **Timeout**: large orgs may need `--task-timeout` above 60m and a higher CPU/memory tier.
