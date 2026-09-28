WITH campaign_days AS (
  SELECT MIN(report_date) AS first_day, MAX(report_date) AS last_day
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
soundlink AS (
  SELECT
    e.engaged_track_isrc AS isrc,
    date_trunc('month', e.report_date) AS month,
    SUM(e.streams) AS soundlink_streams
  FROM campaign_engagement_daily e
  CROSS JOIN campaign_days w
  WHERE e.campaign_id = 'YOUR_CAMPAIGN_ID'
    AND e.engagement_context = 'playlist'
    AND e.report_date BETWEEN w.first_day AND w.last_day
  GROUP BY ALL
),
distributor AS (
  SELECT isrc, month, SUM(streams) AS distributor_streams
  FROM distributor_monthly
  GROUP BY ALL
)
SELECT
  d.isrc,
  d.month,
  COALESCE(s.soundlink_streams, 0) AS soundlink_streams,
  d.distributor_streams,
  ROUND(COALESCE(s.soundlink_streams, 0) / NULLIF(d.distributor_streams, 0), 3) AS attributed_share
FROM distributor d
LEFT JOIN soundlink s USING (isrc, month)
WHERE d.isrc IN (SELECT isrc FROM soundlink)
ORDER BY d.isrc, d.month;
