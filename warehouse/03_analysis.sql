-- Run after table loads and checks. Queries back the walkthrough's four views.

-- Mobility: date and zone are explicit, and unknown geography is visible.
SELECT f.report_date, f.pickup_zone_id, z.zone_name, z.borough, f.trip_count,
       f.zero_distance_trip_count,
       f.base_fare_usd / NULLIF(f.known_base_fare_count, 0) AS avg_base_fare_usd
FROM dbo.FactTaxiDaily f JOIN dbo.DimZone z ON z.zone_id = f.pickup_zone_id
ORDER BY f.report_date, f.trip_count DESC;

-- Air quality: choose one pollutant and unit per chart series.
SELECT f.report_date, f.location_id, l.station_name, f.pollutant_code,
       f.measurement_unit, f.concentration_mean, f.observed_hour_count
FROM dbo.FactAirQualityDaily f JOIN dbo.DimAirLocation l ON l.location_id = f.location_id
ORDER BY f.report_date, f.location_id, f.pollutant_code, f.measurement_unit;

-- Matched date/zone observations: only compare locations with a zone mapping.
-- Each station-day receives equal weight within a zone. The observed station
-- and hour counts let a report show gaps explicitly. No missing data imputation.
DECLARE @minimum_observed_hours int = 18;
WITH pollution_by_zone AS (
    SELECT f.report_date, l.zone_id, f.pollutant_code, f.measurement_unit,
           AVG(f.concentration_mean) AS avg_station_concentration,
           COUNT_BIG(*) AS reporting_station_count,
           SUM(CAST(f.observed_hour_count AS bigint)) AS station_hours
    FROM dbo.FactAirQualityDaily f JOIN dbo.DimAirLocation l ON l.location_id = f.location_id
    WHERE l.zone_id IS NOT NULL AND l.zone_id <> -1
      AND f.observed_hour_count >= @minimum_observed_hours
    GROUP BY f.report_date, l.zone_id, f.pollutant_code, f.measurement_unit
)
SELECT t.report_date, t.pickup_zone_id, p.pollutant_code, p.measurement_unit,
       t.trip_count, p.avg_station_concentration, p.reporting_station_count, p.station_hours
FROM dbo.FactTaxiDaily t JOIN pollution_by_zone p
    ON p.report_date = t.report_date AND p.zone_id = t.pickup_zone_id
ORDER BY t.report_date, t.pickup_zone_id;

-- Economics: show the same eligible charges in both currencies.
SELECT report_date,
       SUM(fx_covered_charge_usd) AS matched_charge_usd,
       SUM(total_charged_eur) AS matched_charge_eur,
       SUM(fx_covered_charge_count) AS fx_covered_charge_count,
       SUM(known_charge_count) AS known_charge_count
FROM dbo.FactTaxiDaily GROUP BY report_date ORDER BY report_date;

-- GDP is displayed separately at the natural annual grain.
SELECT [year], gdp_current_usd
FROM dbo.DimGDP WHERE country_code = 'USA' AND indicator_code = 'NY.GDP.MKTP.CD'
ORDER BY [year];
