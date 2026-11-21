-- Run 01_create_star.sql first. Edit Lakehouse/schema identifiers if needed.
-- Pipeline concurrency must be 1; do not rewrite source Gold during this batch.
-- This publishes the entire configured reporting window as one transaction.
-- No successful run in Fabric is claimed until actual execution is recorded.
BEGIN TRY
    BEGIN TRANSACTION;

    IF NOT EXISTS (SELECT 1 FROM lh_mobility_environment.dbo.gold_fact_taxi_daily)
        THROW 51001, 'Taxi Gold is empty or not synchronized to the SQL endpoint', 1;
    IF NOT EXISTS (SELECT 1 FROM lh_mobility_environment.dbo.gold_fact_air_quality_daily)
        THROW 51002, 'Air-quality Gold is empty; core publication requires real observations', 1;

    IF EXISTS (
        SELECT report_date, pickup_zone_id
        FROM lh_mobility_environment.dbo.gold_fact_taxi_daily
        GROUP BY report_date, pickup_zone_id HAVING COUNT_BIG(*) > 1
    ) THROW 51003, 'Taxi fact grain is not unique', 1;
    IF EXISTS (
        SELECT report_date, location_id, pollutant_code, measurement_unit
        FROM lh_mobility_environment.dbo.gold_fact_air_quality_daily
        GROUP BY report_date, location_id, pollutant_code, measurement_unit HAVING COUNT_BIG(*) > 1
    ) THROW 51004, 'Air-quality fact grain is not unique', 1;

    TRUNCATE TABLE dbo.FactTaxiDaily;
    TRUNCATE TABLE dbo.FactAirQualityDaily;
    TRUNCATE TABLE dbo.DimDate;
    TRUNCATE TABLE dbo.DimZone;
    TRUNCATE TABLE dbo.DimFX;
    TRUNCATE TABLE dbo.DimGDP;
    TRUNCATE TABLE dbo.DimAirLocation;

    INSERT INTO dbo.DimDate (report_date, [year], [month], day_of_week)
    SELECT report_date, [year], [month], day_of_week FROM lh_mobility_environment.dbo.gold_dim_date;
    INSERT INTO dbo.DimZone (zone_id, borough, zone_name, service_zone)
    SELECT zone_id, borough, zone_name, service_zone FROM lh_mobility_environment.dbo.gold_dim_zone;
    INSERT INTO dbo.DimFX (report_date, currency_pair, source_rate_date, usd_per_eur, rate_age_days)
    SELECT report_date, currency_pair, source_rate_date, usd_per_eur, rate_age_days FROM lh_mobility_environment.dbo.gold_dim_fx;
    INSERT INTO dbo.DimGDP (country_code, [year], indicator_code, gdp_current_usd)
    SELECT country_code, [year], indicator_code, gdp_current_usd FROM lh_mobility_environment.dbo.silver_gdp;
    INSERT INTO dbo.DimAirLocation (location_id, station_name, latitude, longitude, zone_id)
    SELECT location_id, station_name, latitude, longitude, zone_id FROM lh_mobility_environment.dbo.gold_dim_air_location;

    INSERT INTO dbo.FactTaxiDaily (
        report_date,pickup_zone_id,trip_count,known_base_fare_count,known_charge_count,
        zero_distance_trip_count,base_fare_usd,total_charged_usd,base_fare_eur,
        total_charged_eur,fx_covered_charge_count,fx_covered_charge_usd)
    SELECT report_date,pickup_zone_id,trip_count,known_base_fare_count,known_charge_count,
        zero_distance_trip_count,base_fare_usd,total_charged_usd,base_fare_eur,
        total_charged_eur,fx_covered_charge_count,fx_covered_charge_usd
    FROM lh_mobility_environment.dbo.gold_fact_taxi_daily;
    INSERT INTO dbo.FactAirQualityDaily (
        report_date,location_id,pollutant_code,measurement_unit,
        observed_hour_count,concentration_sum,concentration_mean)
    SELECT report_date,location_id,pollutant_code,measurement_unit,
        observed_hour_count,concentration_sum,concentration_mean
    FROM lh_mobility_environment.dbo.gold_fact_air_quality_daily;

    IF EXISTS (SELECT report_date FROM dbo.DimDate GROUP BY report_date HAVING COUNT_BIG(*) > 1)
        OR EXISTS (SELECT zone_id FROM dbo.DimZone GROUP BY zone_id HAVING COUNT_BIG(*) > 1)
        OR EXISTS (SELECT report_date,currency_pair FROM dbo.DimFX GROUP BY report_date,currency_pair HAVING COUNT_BIG(*) > 1)
        OR EXISTS (SELECT country_code,[year],indicator_code FROM dbo.DimGDP GROUP BY country_code,[year],indicator_code HAVING COUNT_BIG(*) > 1)
        OR EXISTS (SELECT location_id FROM dbo.DimAirLocation GROUP BY location_id HAVING COUNT_BIG(*) > 1)
        THROW 51005, 'A dimension key is duplicated', 1;

    IF EXISTS (SELECT 1 FROM dbo.FactTaxiDaily f
        LEFT JOIN dbo.DimDate d ON d.report_date=f.report_date
        LEFT JOIN dbo.DimZone z ON z.zone_id=f.pickup_zone_id
        WHERE d.report_date IS NULL OR z.zone_id IS NULL)
        OR EXISTS (SELECT 1 FROM dbo.FactAirQualityDaily f
        LEFT JOIN dbo.DimDate d ON d.report_date=f.report_date
        LEFT JOIN dbo.DimAirLocation l ON l.location_id=f.location_id
        WHERE d.report_date IS NULL OR l.location_id IS NULL)
        THROW 51006, 'A fact contains a missing dimension reference', 1;

    IF (SELECT COUNT_BIG(*) FROM dbo.FactTaxiDaily) <>
       (SELECT COUNT_BIG(*) FROM lh_mobility_environment.dbo.gold_fact_taxi_daily)
        OR (SELECT COUNT_BIG(*) FROM dbo.FactAirQualityDaily) <>
       (SELECT COUNT_BIG(*) FROM lh_mobility_environment.dbo.gold_fact_air_quality_daily)
        THROW 51007, 'Warehouse row counts differ from Gold', 1;

    IF EXISTS (
        SELECT SUM(base_fare_usd), SUM(total_charged_usd), SUM(trip_count) FROM dbo.FactTaxiDaily
        EXCEPT
        SELECT SUM(base_fare_usd), SUM(total_charged_usd), SUM(trip_count)
        FROM lh_mobility_environment.dbo.gold_fact_taxi_daily
    ) THROW 51008, 'Warehouse measures differ from Gold', 1;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
