from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from soundlink_warehouse_connector.loaders.duckdb import DuckDbLoader

EXAMPLE = Path(__file__).parent.parent / "examples" / "playlist-impact"
CAMPAIGN_ID = "cmp-1"

# Playlist tracks: (isrc, spotify_id, position, streams per day per country).
# ISRC_X is played from the playlist context but is not on the playlist.
TRACKS = [
    ("ISRC_A", "sp_a", 3, 20),
    ("ISRC_B", "sp_b", 15, 8),
    ("ISRC_C", "sp_c", 40, 2),
    ("ISRC_D", "sp_d", 50, 1),
    ("ISRC_X", "sp_x", None, 3),
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
    # Spend Aug 10 - Sep 8, $10/day in US and DE.
    conn.execute(
        """
        INSERT INTO campaign_country_daily
          (provider, account_id, report_date, campaign_id, country_code,
           campaign_target_type, campaign_target_playlist_id, spend_total, currency,
           raw_json, synced_at)
        SELECT 'soundlink', 'org-1', d::DATE, ?, c, 'playlist', 'pl-1', 10.0, 'USD', '{}', now()
        FROM generate_series(DATE '2026-08-10', DATE '2026-09-08', INTERVAL 1 DAY) t(d),
             (VALUES ('US'), ('DE')) v(c)
        """,
        [CAMPAIGN_ID],
    )
    # Engagement runs 7 days past the last spend day; some spend days are labeled
    # 'ended', so the window must come from spend, not status.
    for isrc, spotify_id, position, daily in TRACKS:
        conn.execute(
            """
            INSERT INTO campaign_engagement_daily
              (provider, account_id, report_date, campaign_id, engagement_context,
               country_code, engaged_spotify_track_id, campaign_target_type,
               campaign_target_playlist_id, status, engaged_track_isrc, playlist_position,
               new_listeners, returning_listeners, listeners, new_listener_streams,
               returning_listener_streams, streams, raw_json, synced_at)
            SELECT 'soundlink', 'org-1', d::DATE, ?, 'playlist', c, ?, 'playlist', 'pl-1',
                   CASE WHEN d::DATE > DATE '2026-09-01' THEN 'ended' ELSE 'active' END,
                   ?, ?, 1, 1, 2, 1, 1, ?, '{}', now()
            FROM generate_series(DATE '2026-08-10', DATE '2026-09-15', INTERVAL 1 DAY) t(d),
                 (VALUES ('US'), ('DE')) v(c)
            """,
            [CAMPAIGN_ID, spotify_id, isrc, position, daily],
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


def test_attributed_share_uses_spend_window_and_guards_zero(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    rows = {(r[0], str(r[1])): r[2:] for r in _run(conn, "03_attributed_share.sql")}

    # 22 days x 2 countries x 20 in August; 8 spend days in September.
    assert rows[("ISRC_A", "2026-08-01")] == (880, 6400, 0.138)
    assert rows[("ISRC_A", "2026-09-01")] == (320, 6000, 0.053)
    assert rows[("ISRC_A", "2026-07-01")] == (0, 4000, 0.0)
    assert rows[("ISRC_A", "2026-11-01")] == (0, 0, None)
    assert rows[("ISRC_D", "2026-08-01")] == (44, 0, None)
    assert not any(isrc == "ISRC_X" for isrc, _ in rows)


def test_position_bands_count_campaign_days_only(conn: duckdb.DuckDBPyConnection) -> None:
    assert _run(conn, "04_position_bands.sql") == [
        ("01-10", 30, 1200, 40.0),
        ("11-25", 30, 480, 16.0),
        ("26+", 60, 180, 3.0),
    ]


def test_before_during_after_uses_statement_only(conn: duckdb.DuckDBPyConnection) -> None:
    assert _run(conn, "05_before_during_after.sql") == [
        ("1_before", 1, 6100, 6100.0),
        ("2_during", 2, 18910, 9455.0),
        ("3_after", 2, 7320, 3660.0),
    ]


def test_recoup_estimate_prices_campaign_streams(conn: duckdb.DuckDBPyConnection) -> None:
    # (880 + 320 + 352 + 128 + 88 + 32) streams x $0.003; ISRC_D has no rate.
    assert _run(conn, "06_recoup_estimate.sql") == [(5.4, 600.0, 0.009)]
