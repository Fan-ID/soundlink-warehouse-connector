WITH campaign_days AS (
  SELECT MIN(report_date) AS first_day, MAX(report_date) AS last_day
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
soundlink AS (
  SELECT
    CASE
      WHEN e.engaged_spotify_track_id = e.campaign_target_spotify_track_id THEN 'promoted'
      WHEN e.engaged_track_isrc = e.campaign_target_isrc THEN 'promoted'
      ELSE 'other_releases'
    END AS bucket,
    e.engaged_track_isrc AS isrc,
    CAST(date_trunc('month', e.report_date) AS DATE) AS month,
    SUM(e.streams) AS soundlink_streams
  FROM campaign_engagement_daily e
  CROSS JOIN campaign_days w
  WHERE e.campaign_id = 'YOUR_CAMPAIGN_ID'
    AND e.campaign_target_type = 'track'
    AND e.engagement_context = 'catalog'
    AND e.engaged_track_isrc IS NOT NULL
    AND e.campaign_target_spotify_track_id IS NOT NULL
    AND e.report_date BETWEEN w.first_day AND w.last_day
  GROUP BY ALL
),
distributor AS (
  SELECT isrc, month, SUM(streams) AS distributor_streams
  FROM distributor_monthly
  GROUP BY ALL
)
SELECT
  s.bucket,
  s.isrc,
  s.month,
  s.soundlink_streams,
  d.distributor_streams,
  ROUND(s.soundlink_streams / NULLIF(d.distributor_streams, 0), 3) AS attributed_share
FROM soundlink s
LEFT JOIN distributor d USING (isrc, month)
ORDER BY s.bucket, s.isrc, s.month;
