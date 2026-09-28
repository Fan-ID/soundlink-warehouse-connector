WITH spend_window AS (
  SELECT
    date_trunc('month', MIN(report_date)) AS first_month,
    date_trunc('month', MAX(report_date)) AS last_month
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
own_tracks AS (
  SELECT DISTINCT engaged_track_isrc AS isrc
  FROM campaign_engagement_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND engagement_context = 'playlist'
    AND playlist_position IS NOT NULL
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
JOIN own_tracks USING (isrc)
CROSS JOIN spend_window w
GROUP BY ALL
ORDER BY period;
