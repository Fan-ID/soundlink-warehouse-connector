WITH campaign_days AS (
  SELECT
    MIN(report_date) AS first_day,
    MAX(report_date) AS last_day,
    date_trunc('month', MIN(report_date)) AS first_month,
    date_trunc('month', MAX(report_date)) AS last_month
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
promoted AS (
  SELECT SUM(e.streams) AS promoted_streams
  FROM campaign_engagement_daily e
  CROSS JOIN campaign_days w
  WHERE e.campaign_id = 'YOUR_CAMPAIGN_ID'
    AND e.campaign_target_type = 'track'
    AND e.engagement_context = 'catalog'
    AND e.engaged_track_isrc IS NOT NULL
    AND e.campaign_target_spotify_track_id IS NOT NULL
    AND (
      e.engaged_spotify_track_id = e.campaign_target_spotify_track_id
      OR e.engaged_track_isrc = e.campaign_target_isrc
    )
    AND e.report_date BETWEEN w.first_day AND w.last_day
),
other_release_tracks AS (
  SELECT e.engaged_track_isrc AS isrc
  FROM campaign_engagement_daily e
  CROSS JOIN campaign_days w
  CROSS JOIN promoted p
  WHERE e.campaign_id = 'YOUR_CAMPAIGN_ID'
    AND e.campaign_target_type = 'track'
    AND e.engagement_context = 'catalog'
    AND e.engaged_track_isrc IS NOT NULL
    AND e.campaign_target_spotify_track_id IS NOT NULL
    AND e.engaged_spotify_track_id IS DISTINCT FROM e.campaign_target_spotify_track_id
    AND e.engaged_track_isrc IS DISTINCT FROM e.campaign_target_isrc
    AND e.report_date BETWEEN w.first_day AND w.last_day
  GROUP BY e.engaged_track_isrc, p.promoted_streams
  HAVING SUM(e.streams) >= 0.05 * p.promoted_streams
)
SELECT
  CASE
    WHEN d.month < w.first_month THEN '1_before'
    WHEN d.month <= w.last_month THEN '2_during'
    ELSE '3_after'
  END AS period,
  COUNT(DISTINCT d.month) AS months,
  SUM(d.streams) AS distributor_streams,
  ROUND(SUM(d.streams) / COUNT(DISTINCT d.month)) AS streams_per_month
FROM distributor_monthly d
JOIN other_release_tracks USING (isrc)
CROSS JOIN campaign_days w
GROUP BY ALL
ORDER BY period;
