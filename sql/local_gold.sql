-- Explicit report bounds come from the one-row run_config table.
CREATE OR REPLACE TABLE dim_date AS
SELECT CAST(day AS DATE) AS report_date,
       CAST(date_part('year', day) AS INTEGER) AS year,
       CAST(date_part('month', day) AS INTEGER) AS month,
       CAST(date_part('dow', day) + 1 AS INTEGER) AS day_of_week
FROM run_config, generate_series(start_date, end_date, INTERVAL '1 day') AS t(day);

CREATE OR REPLACE TABLE dim_fx AS
SELECT d.report_date, 'USD/EUR' AS currency_pair,
       f.source_rate_date, f.usd_per_eur,
       date_diff('day', f.source_rate_date, d.report_date) AS rate_age_days
FROM dim_date d LEFT JOIN silver_fx f
 ON f.source_rate_date <= d.report_date AND f.is_valid_rate
 AND date_diff('day', f.source_rate_date, d.report_date) <= (SELECT max_fx_age_days FROM run_config)
QUALIFY row_number() OVER (PARTITION BY d.report_date ORDER BY f.source_rate_date DESC NULLS LAST) = 1;

CREATE OR REPLACE VIEW reporting_taxi AS
SELECT t.*, coalesce(z.zone_id, -1) AS pickup_zone_id
FROM silver_taxi t LEFT JOIN dim_zone z ON z.zone_id = t.original_zone_id
WHERE t.pickup_date BETWEEN (SELECT start_date FROM run_config) AND (SELECT end_date FROM run_config);

CREATE OR REPLACE TABLE fact_taxi_daily AS
WITH totals AS (
 SELECT pickup_date AS report_date, pickup_zone_id,
   count(*)::BIGINT AS trip_count,
   count(fare_usd)::BIGINT AS known_base_fare_count,
   count(total_charged_usd)::BIGINT AS known_charge_count,
   count(*) FILTER (WHERE distance_miles = 0)::BIGINT AS zero_distance_trip_count,
   sum(fare_usd) AS base_fare_usd, sum(total_charged_usd) AS total_charged_usd
 FROM reporting_taxi GROUP BY pickup_date, pickup_zone_id
)
SELECT t.*,
 CAST(t.base_fare_usd / f.usd_per_eur AS DECIMAL(28,4)) AS base_fare_eur,
 CAST(t.total_charged_usd / f.usd_per_eur AS DECIMAL(28,4)) AS total_charged_eur,
 CASE WHEN f.usd_per_eur IS NOT NULL THEN t.known_charge_count ELSE 0 END AS fx_covered_charge_count,
 CASE WHEN f.usd_per_eur IS NOT NULL THEN t.total_charged_usd END AS fx_covered_charge_usd
FROM totals t LEFT JOIN dim_fx f USING(report_date);

CREATE OR REPLACE TABLE taxi_hourly AS
SELECT pickup_date AS report_date, pickup_hour, pickup_zone_id, count(*)::BIGINT AS trip_count
FROM reporting_taxi GROUP BY pickup_date, pickup_hour, pickup_zone_id;

CREATE OR REPLACE TABLE mobility_daily AS
SELECT d.report_date,
 coalesce(sum(f.trip_count), 0)::BIGINT AS trip_count,
 sum(f.base_fare_usd) AS base_fare_usd, sum(f.total_charged_usd) AS total_charged_usd,
 sum(f.base_fare_usd) / nullif(sum(f.known_base_fare_count), 0) AS avg_base_fare_usd,
 coalesce(sum(f.zero_distance_trip_count), 0)::BIGINT AS zero_distance_trip_count,
 sum(f.fx_covered_charge_usd) AS matched_charge_usd, sum(f.total_charged_eur) AS matched_charge_eur,
 sum(f.fx_covered_charge_count) AS fx_covered_charge_count
FROM dim_date d LEFT JOIN fact_taxi_daily f USING(report_date)
GROUP BY d.report_date ORDER BY d.report_date;
