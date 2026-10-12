WITH campaign_days AS (
  SELECT MIN(report_date) AS first_day, MAX(report_date) AS last_day
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
    AND spend_total > 0
),
spend AS (
  SELECT SUM(spend_total) AS spend_usd
  FROM campaign_country_daily
  WHERE campaign_id = 'YOUR_CAMPAIGN_ID'
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
rate AS (
  SELECT isrc, month, SUM(revenue) / NULLIF(SUM(streams), 0) AS revenue_per_stream
  FROM distributor_monthly
  WHERE currency = 'USD'
  GROUP BY ALL
)
SELECT
  s.bucket,
  ROUND(SUM(s.soundlink_streams * r.revenue_per_stream), 2) AS attributed_revenue_estimate,
  ANY_VALUE(spend.spend_usd) AS spend_usd,
  ROUND(
    SUM(s.soundlink_streams * r.revenue_per_stream) / ANY_VALUE(spend.spend_usd),
    3
  ) AS recoup_ratio
FROM soundlink s
JOIN rate r USING (isrc, month)
CROSS JOIN spend
GROUP BY s.bucket
ORDER BY s.bucket;
