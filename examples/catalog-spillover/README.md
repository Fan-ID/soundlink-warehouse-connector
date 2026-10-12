# Catalog spillover with distributor data

SQL for splitting a Soundlink track campaign into the promoted recording and other releases, then joining both to your distributor statement by ISRC and month. Written for DuckDB against the tables this connector creates.

| File                         | Answers                                                                                                   |
| ---------------------------- | --------------------------------------------------------------------------------------------------------- |
| `02_load_statement.sql`      | Loads your statement CSV into `distributor_monthly`, Spotify rows only                                    |
| `03_promoted_vs_other.sql`   | Promoted ISRC vs other releases from connected listeners                                                  |
| `04_attributed_share.sql`    | What share of each ISRC's Spotify streams came from campaign listeners, per month                         |
| `05_before_during_after.sql` | Statement streams per month on the other-release ISRCs that actually moved                                |
| `06_recoup_estimate.sql`     | Rough recoup ratio per bucket: campaign streams priced at your statement's revenue per stream, over spend |

Numbering follows the steps of the guide; step 1 is running the sync.

## Run

1. Sync your campaigns: `uv run soundlink-sync sync --mode full`.
2. Map your statement to `isrc, store, sale_month (YYYY-MM), country_code, streams, revenue, currency`, rename Spotify rows so `store` is exactly `Spotify`, and save it as `distributor_statements.csv` in the directory you run from. `distributor_statements.sample.csv` shows the shape.
3. Replace `YOUR_CAMPAIGN_ID` in the query files with a **track** campaign ID, then run them in order:

```bash
uv run python -c "import duckdb, sys; print(duckdb.connect('data/soundlink.duckdb').sql(open(sys.argv[1]).read()))" examples/catalog-spillover/03_promoted_vs_other.sql
```

Any DuckDB client works; the `duckdb` CLI can run the files directly.

## Read before trusting the numbers

- `engagement_context = 'catalog'` includes the promoted track. Split on Spotify track id, then ISRC.
- Soundlink only counts plays from listeners who connected Spotify through the campaign soundlink. Treat both buckets as a floor.
- Query 5 keeps other-release ISRCs that did at least 5% of the promoted track's Soundlink streams in the spend window. Raise that if you only want the two or three finance would put next to spend. Recoup (query 6) does not use that cut: it prices the Soundlink streams, so a handful of plays on a catalog hit is cents.
- Same recording on the single and the album, same ISRC: promoted, not spillover.
- Query 4 shows statement months before and after the campaign as zeros, not missing rows. Use the sale month, not the statement month, and wait until it covers at least a month past the campaign.
- Leave the last 7 days out of conclusions; rows can still change.
- The recoup query assumes USD on both sides and is an estimate, not an audit. Add the two `recoup_ratio` values; do not add `spend_usd`.

`tests/test_examples_catalog_spillover.py` runs every file against the connector schema, so a schema change that breaks them fails `uv run pytest`.
