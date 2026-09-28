# Playlist impact with distributor data

SQL for joining Soundlink playlist campaign engagement with your distributor statement, by ISRC and month. Written for DuckDB against the tables this connector creates.

| File | Answers |
| --- | --- |
| `02_load_statement.sql` | Loads your statement CSV into `distributor_monthly`, Spotify rows only |
| `03_attributed_share.sql` | What share of each track's Spotify streams came from campaign listeners, per month |
| `04_position_bands.sql` | Streams per track-day by playlist slot band |
| `05_before_during_after.sql` | Statement streams per month before, during and after the campaign |
| `06_recoup_estimate.sql` | Rough recoup ratio: campaign streams priced at your statement's revenue per stream, over spend |

Numbering follows the steps of the guide; step 1 is running the sync.

## Run

1. Sync your campaigns: `uv run soundlink-sync sync --mode full`.
2. Map your statement to `isrc, store, sale_month (YYYY-MM), country_code, streams, revenue, currency`, rename Spotify rows so `store` is exactly `Spotify`, and save it as `distributor_statements.csv` in the directory you run from. `distributor_statements.sample.csv` shows the shape.
3. Replace `YOUR_CAMPAIGN_ID` in the query files with your campaign ID, then run them in order:

```bash
uv run python -c "import duckdb, sys; print(duckdb.connect('data/soundlink.duckdb').sql(open(sys.argv[1]).read()))" examples/playlist-impact/03_attributed_share.sql
```

Any DuckDB client works; the `duckdb` CLI can run the files directly.

## Read before trusting the numbers

- Soundlink only counts plays from listeners who connected Spotify through the campaign soundlink, played from the campaign playlist. Treat it as mostly a floor.
- Use the statement's sale month, not the statement month, and wait until it covers at least a month past the campaign.
- Leave the last 7 days out of conclusions; rows can still change.
- The recoup query assumes USD on both sides and is an estimate, not an audit.

`tests/test_examples_playlist_impact.py` runs every file against the connector schema, so a schema change that breaks them fails `uv run pytest`.
