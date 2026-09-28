CREATE OR REPLACE TABLE distributor_monthly AS
SELECT
  isrc,
  CAST(sale_month || '-01' AS DATE) AS month,
  country_code,
  streams,
  revenue,
  currency
FROM read_csv_auto('distributor_statements.csv')
WHERE store = 'Spotify';
