WITH campaign_days AS (
  SELECT MIN(report_date) AS first_day, MAX(report_date) AS last_day
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
track_days AS (
  SELECT
    e.report_date,
    e.engaged_track_isrc AS isrc,
    MIN(e.playlist_position) AS playlist_position,
    SUM(e.streams) AS streams
  FROM campaign_engagement_daily e
  CROSS JOIN campaign_days w
  WHERE e.campaign_id = 'YOUR_CAMPAIGN_ID'
    AND e.engagement_context = 'playlist'
    AND e.playlist_position IS NOT NULL
    AND e.report_date BETWEEN w.first_day AND w.last_day
  GROUP BY ALL
)
SELECT
  CASE
    WHEN playlist_position <= 10 THEN '01-10'
    WHEN playlist_position <= 25 THEN '11-25'
    ELSE '26+'
  END AS position_band,
  COUNT(*) AS track_days,
  SUM(streams) AS streams,
  ROUND(AVG(streams), 1) AS streams_per_track_day
FROM track_days
GROUP BY ALL
ORDER BY position_band;
