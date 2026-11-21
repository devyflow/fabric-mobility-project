-- Runs in DuckDB for local verification. The Fabric notebook uses PySpark.
-- Keep original fields and original file/row position as lineage.
CREATE OR REPLACE TABLE silver_taxi AS
WITH typed AS (
 SELECT *, try_cast(tpep_pickup_datetime AS TIMESTAMP) AS pickup_ts,
   try_cast(tpep_dropoff_datetime AS TIMESTAMP) AS dropoff_ts,
   try_cast(fare_amount AS DECIMAL(18,4)) AS fare_usd,
   try_cast(total_amount AS DECIMAL(18,4)) AS total_charged_usd,
   try_cast(trip_distance AS DOUBLE) AS distance_miles,
   try_cast(PULocationID AS INTEGER) AS original_zone_id
 FROM source_taxi
), enriched AS (
 SELECT *, CAST(pickup_ts AS DATE) AS pickup_date,
   CAST(date_part('hour', pickup_ts) AS INTEGER) AS pickup_hour,
   date_diff('second', pickup_ts, dropoff_ts) AS duration_seconds
 FROM typed
)
SELECT *, list_filter([
 CASE WHEN distance_miles IS NULL THEN 'missing_distance' END,
 CASE WHEN distance_miles IS NOT NULL AND NOT isfinite(distance_miles) THEN 'nonfinite_distance' END,
 CASE WHEN distance_miles = 0 THEN 'zero_distance' END,
 CASE WHEN distance_miles < 0 THEN 'negative_distance' END,
 CASE WHEN fare_usd IS NULL THEN 'missing_fare' END,
 CASE WHEN fare_usd < 0 THEN 'negative_fare_review' END,
 CASE WHEN duration_seconds IS NULL THEN 'missing_duration' END,
 CASE WHEN duration_seconds < 0 THEN 'negative_duration' END,
 CASE WHEN fare_amount IS NOT NULL AND fare_usd IS NULL THEN 'fare_parse_error' END,
 CASE WHEN total_amount IS NOT NULL AND total_charged_usd IS NULL THEN 'total_parse_error' END,
 CASE WHEN trip_distance IS NOT NULL AND distance_miles IS NULL THEN 'distance_parse_error' END,
 CASE WHEN tpep_pickup_datetime IS NOT NULL AND pickup_ts IS NULL THEN 'pickup_parse_error' END,
 CASE WHEN tpep_dropoff_datetime IS NOT NULL AND dropoff_ts IS NULL THEN 'dropoff_parse_error' END
 ], lambda value: value IS NOT NULL) AS quality_flags
FROM enriched;
