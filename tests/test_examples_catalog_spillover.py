from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from soundlink_warehouse_connector.loaders.duckdb import DuckDbLoader

EXAMPLE = Path(__file__).parent.parent / "examples" / "catalog-spillover"
CAMPAIGN_ID = "cmp-track-1"
TARGET_ISRC = "ISRC_A"
TARGET_SPOTIFY_ID = "sp_a"

# Catalog tracks: (isrc, spotify_id, streams per day per country).
# ISRC_A is the promoted recording. ISRC_N is a catalog hit that barely
# appears in Soundlink and must stay out of before/during/after.
TRACKS = [
    ("ISRC_A", "sp_a", 20),
    ("ISRC_B", "sp_b", 8),
    ("ISRC_C", "sp_c", 2),
    ("ISRC_D", "sp_d", 1),
]


def _run(conn: duckdb.DuckDBPyConnection, name: str) -> list[tuple]:
    sql = (EXAMPLE / name).read_text(encoding="utf-8")
    sql = sql.replace("YOUR_CAMPAIGN_ID", CAMPAIGN_ID).replace(
        "'distributor_statements.csv'",
        f"'{EXAMPLE / 'distributor_statements.sample.csv'}'",
    )
    result = conn.execute(sql)
    return result.fetchall() if result.description else []


@pytest.fixture
def conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db_path = tmp_path / "soundlink.duckdb"
    loader = DuckDbLoader(db_path)
    loader.ensure_schema()
    loader.close()

    conn = duckdb.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO campaign_country_daily
          (provider, account_id, report_date, campaign_id, country_code,
           campaign_target_type, campaign_target_isrc, campaign_target_spotify_track_id,
           spend_total, currency, raw_json, synced_at)
        SELECT 'soundlink', 'org-1', d::DATE, ?, c, 'track', ?, ?, 10.0, 'USD', '{}', now()
        FROM generate_series(DATE '2026-08-10', DATE '2026-09-08', INTERVAL 1 DAY) t(d),
             (VALUES ('US'), ('DE')) v(c)
        """,
        [CAMPAIGN_ID, TARGET_ISRC, TARGET_SPOTIFY_ID],
    )
    for isrc, spotify_id, daily in TRACKS:
        conn.execute(
            """
            INSERT INTO campaign_engagement_daily
              (provider, account_id, report_date, campaign_id, engagement_context,
               country_code, engaged_spotify_track_id, campaign_target_type,
               campaign_target_isrc, campaign_target_spotify_track_id, status,
               engaged_track_isrc, playlist_position, new_listeners, returning_listeners,
               listeners, new_listener_streams, returning_listener_streams, streams,
               raw_json, synced_at)
            SELECT 'soundlink', 'org-1', d::DATE, ?, 'catalog', c, ?, 'track', ?, ?,
                   CASE WHEN d::DATE > DATE '2026-09-01' THEN 'ended' ELSE 'active' END,
                   ?, NULL, 1, 1, 2, 1, 1, ?, '{}', now()
            FROM generate_series(DATE '2026-08-10', DATE '2026-09-15', INTERVAL 1 DAY) t(d),
                 (VALUES ('US'), ('DE')) v(c)
            """,
            [CAMPAIGN_ID, spotify_id, TARGET_ISRC, TARGET_SPOTIFY_ID, isrc, daily],
        )
    conn.execute(
        """
        INSERT INTO campaign_engagement_daily
          (provider, account_id, report_date, campaign_id, engagement_context,
           country_code, engaged_spotify_track_id, campaign_target_type,
           campaign_target_isrc, campaign_target_spotify_track_id, status,
           engaged_track_isrc, playlist_position, new_listeners, returning_listeners,
           listeners, new_listener_streams, returning_listener_streams, streams,
           raw_json, synced_at)
        SELECT 'soundlink', 'org-1', d::DATE, ?, 'catalog', c, 'sp_n', 'track', ?, ?,
               'active', 'ISRC_N', NULL, 1, 0, 1, 1, 0, 1, '{}', now()
        FROM generate_series(DATE '2026-08-10', DATE '2026-08-12', INTERVAL 1 DAY) t(d),
             (VALUES ('US'), ('DE')) v(c)
        """,
        [CAMPAIGN_ID, TARGET_ISRC, TARGET_SPOTIFY_ID],
    )
    _run(conn, "02_load_statement.sql")
    yield conn
    conn.close()


def test_load_statement_keeps_spotify_rows_only(conn: duckdb.DuckDBPyConnection) -> None:
    total = conn.execute(
        "SELECT SUM(streams) FROM distributor_monthly "
        "WHERE isrc = 'ISRC_A' AND month = DATE '2026-08-01'"
    ).fetchone()
    assert total == (6400,)


def test_promoted_vs_other_splits_on_spotify_id(conn: duckdb.DuckDBPyConnection) -> None:
    rows = {(r[0], r[1]): r[3] for r in _run(conn, "03_promoted_vs_other.sql")}
    assert rows[("promoted", "ISRC_A")] == 1200
    assert rows[("other_releases", "ISRC_B")] == 480
    assert rows[("other_releases", "ISRC_C")] == 120
    assert rows[("other_releases", "ISRC_D")] == 60
    assert rows[("other_releases", "ISRC_N")] == 6


def test_same_isrc_different_spotify_id_stays_promoted(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    conn.execute(
        """
        INSERT INTO campaign_engagement_daily
          (provider, account_id, report_date, campaign_id, engagement_context,
           country_code, engaged_spotify_track_id, campaign_target_type,
           campaign_target_isrc, campaign_target_spotify_track_id, status,
           engaged_track_isrc, playlist_position, new_listeners, returning_listeners,
           listeners, new_listener_streams, returning_listener_streams, streams,
           raw_json, synced_at)
        VALUES (
          'soundlink', 'org-1', DATE '2026-08-15', ?, 'catalog', 'US', 'sp_a_album',
          'track', ?, ?, 'active', ?, NULL, 1, 0, 1, 4, 0, 4, '{}', now()
        )
        """,
        [CAMPAIGN_ID, TARGET_ISRC, TARGET_SPOTIFY_ID, TARGET_ISRC],
    )
    rows = {(r[0], r[1]): r[3] for r in _run(conn, "03_promoted_vs_other.sql")}
    assert rows[("promoted", "ISRC_A")] == 1204
    assert ("other_releases", "ISRC_A") not in rows


def test_attributed_share_uses_spend_window(conn: duckdb.DuckDBPyConnection) -> None:
    rows = {(r[0], r[1], str(r[2])): r[3:] for r in _run(conn, "04_attributed_share.sql")}

    # 22 spend days in August, 8 in September. Engagement rows run through
    # Sep 15; if the window used those days, September promoted would be 600.
    assert rows[("promoted", "ISRC_A", "2026-08-01")] == (880, 6400, 0.138)
    assert rows[("promoted", "ISRC_A", "2026-09-01")] == (320, 6000, 0.053)
    assert rows[("promoted", "ISRC_A", "2026-07-01")] == (0, 4000, 0.0)
    assert rows[("promoted", "ISRC_A", "2026-10-01")] == (0, 4800, 0.0)
    assert rows[("promoted", "ISRC_A", "2026-11-01")] == (0, 0, None)
    assert rows[("other_releases", "ISRC_B", "2026-08-01")] == (352, 2400, 0.147)
    assert rows[("other_releases", "ISRC_D", "2026-08-01")] == (44, 0, None)
    assert rows[("other_releases", "ISRC_N", "2026-07-01")] == (0, 20000, 0.0)
    assert rows[("other_releases", "ISRC_N", "2026-08-01")] == (6, 22000, 0.0)
    assert rows[("other_releases", "ISRC_N", "2026-09-01")] == (0, 21000, 0.0)


def test_before_during_after_drops_noise_isrcs(conn: duckdb.DuckDBPyConnection) -> None:
    # ISRC_N is 0.5% of promoted Soundlink streams and would dominate the
    # statement if included (20k+/month). 5% of 1200 = 60, so B/C/D stay.
    assert _run(conn, "05_before_during_after.sql") == [
        ("1_before", 1, 2100, 2100.0),
        ("2_during", 2, 6510, 3255.0),
        ("3_after", 1, 2520, 2520.0),
    ]


def test_recoup_estimate_is_per_bucket(conn: duckdb.DuckDBPyConnection) -> None:
    rows = {r[0]: r[1:] for r in _run(conn, "06_recoup_estimate.sql")}
    # ISRC_N's 6 streams still price (~$0.02). The 5% cut is only on
    # before/during/after, where that ISRC's statement totals would dominate.
    assert rows["other_releases"] == (1.82, 600.0, 0.003)
    assert rows["promoted"] == (3.6, 600.0, 0.006)
