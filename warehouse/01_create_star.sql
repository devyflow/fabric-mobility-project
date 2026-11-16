-- Run in the Fabric Warehouse, not the read-only Lakehouse SQL endpoint.
-- Declared grains are validated at load time before publishing. In Fabric,
-- informational constraints alone would not reject duplicate keys.
IF OBJECT_ID('dbo.DimDate', 'U') IS NULL
    CREATE TABLE dbo.DimDate (
        report_date date NOT NULL, [year] int NOT NULL, [month] int NOT NULL,
        day_of_week int NOT NULL
    );

IF OBJECT_ID('dbo.DimZone', 'U') IS NULL
    CREATE TABLE dbo.DimZone (
        zone_id int NOT NULL, borough varchar(100), zone_name varchar(200),
        service_zone varchar(100)
    );

IF OBJECT_ID('dbo.DimFX', 'U') IS NULL
    CREATE TABLE dbo.DimFX (
        report_date date NOT NULL, currency_pair varchar(12) NOT NULL,
        source_rate_date date, usd_per_eur decimal(18,8), rate_age_days int
    );

IF OBJECT_ID('dbo.DimGDP', 'U') IS NULL
    CREATE TABLE dbo.DimGDP (
        country_code varchar(3) NOT NULL, [year] int NOT NULL,
        indicator_code varchar(50) NOT NULL, gdp_current_usd decimal(28,2)
    );

IF OBJECT_ID('dbo.DimAirLocation', 'U') IS NULL
    CREATE TABLE dbo.DimAirLocation (
        location_id int NOT NULL, station_name varchar(200),
        latitude decimal(10,6), longitude decimal(10,6), zone_id int
    );

IF OBJECT_ID('dbo.FactTaxiDaily', 'U') IS NULL
    CREATE TABLE dbo.FactTaxiDaily (
        report_date date NOT NULL, pickup_zone_id int NOT NULL,
        trip_count bigint NOT NULL, known_base_fare_count bigint NOT NULL,
        known_charge_count bigint NOT NULL, zero_distance_trip_count bigint NOT NULL,
        base_fare_usd decimal(28,4), total_charged_usd decimal(28,4),
        base_fare_eur decimal(28,4), total_charged_eur decimal(28,4),
        fx_covered_charge_count bigint NOT NULL, fx_covered_charge_usd decimal(28,4)
    );

IF OBJECT_ID('dbo.FactAirQualityDaily', 'U') IS NULL
    CREATE TABLE dbo.FactAirQualityDaily (
        report_date date NOT NULL, location_id int NOT NULL, pollutant_code varchar(40) NOT NULL,
        measurement_unit varchar(60) NOT NULL, observed_hour_count int NOT NULL,
        concentration_sum float NOT NULL, concentration_mean float NOT NULL
    );
