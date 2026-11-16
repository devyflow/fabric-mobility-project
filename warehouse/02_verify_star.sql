-- Expected: 0 rows from each exception query, after all Warehouse loads succeed.
-- Empty tables also produce zero exceptions; the row counts below are required evidence.
SELECT 'FactTaxiDaily' AS table_name, COUNT_BIG(*) AS row_count FROM dbo.FactTaxiDaily
UNION ALL SELECT 'FactAirQualityDaily', COUNT_BIG(*) FROM dbo.FactAirQualityDaily
UNION ALL SELECT 'DimDate', COUNT_BIG(*) FROM dbo.DimDate
UNION ALL SELECT 'DimZone', COUNT_BIG(*) FROM dbo.DimZone
UNION ALL SELECT 'DimFX', COUNT_BIG(*) FROM dbo.DimFX
UNION ALL SELECT 'DimGDP', COUNT_BIG(*) FROM dbo.DimGDP
UNION ALL SELECT 'DimAirLocation', COUNT_BIG(*) FROM dbo.DimAirLocation;

SELECT report_date, pickup_zone_id, COUNT_BIG(*) AS duplicate_rows
FROM dbo.FactTaxiDaily GROUP BY report_date, pickup_zone_id HAVING COUNT_BIG(*) > 1;

SELECT report_date, location_id, pollutant_code, measurement_unit, COUNT_BIG(*) AS duplicate_rows
FROM dbo.FactAirQualityDaily
GROUP BY report_date, location_id, pollutant_code, measurement_unit HAVING COUNT_BIG(*) > 1;

SELECT report_date FROM dbo.DimDate GROUP BY report_date HAVING COUNT_BIG(*) > 1;
SELECT zone_id FROM dbo.DimZone GROUP BY zone_id HAVING COUNT_BIG(*) > 1;
SELECT report_date, currency_pair FROM dbo.DimFX
GROUP BY report_date, currency_pair HAVING COUNT_BIG(*) > 1;
SELECT country_code, [year], indicator_code FROM dbo.DimGDP
GROUP BY country_code, [year], indicator_code HAVING COUNT_BIG(*) > 1;
SELECT location_id FROM dbo.DimAirLocation GROUP BY location_id HAVING COUNT_BIG(*) > 1;

SELECT f.report_date, f.pickup_zone_id FROM dbo.FactTaxiDaily f
LEFT JOIN dbo.DimDate d ON f.report_date = d.report_date
LEFT JOIN dbo.DimZone z ON f.pickup_zone_id = z.zone_id
WHERE d.report_date IS NULL OR z.zone_id IS NULL;

SELECT f.report_date, f.location_id FROM dbo.FactAirQualityDaily f
LEFT JOIN dbo.DimDate d ON f.report_date = d.report_date
LEFT JOIN dbo.DimAirLocation a ON f.location_id = a.location_id
WHERE d.report_date IS NULL OR a.location_id IS NULL;

SELECT * FROM dbo.DimFX
WHERE source_rate_date > report_date OR usd_per_eur <= 0
    OR (source_rate_date IS NOT NULL AND DATEDIFF(day, source_rate_date, report_date) <> rate_age_days);

-- Explain: divide totals by matched trip counts. Missing FX never becomes zero.
SELECT report_date,
    SUM(trip_count) AS trips,
    SUM(zero_distance_trip_count) AS zero_distance_trips,
    SUM(base_fare_usd) / NULLIF(SUM(known_base_fare_count), 0) AS avg_base_fare_usd,
    SUM(fx_covered_charge_usd) / NULLIF(SUM(fx_covered_charge_count), 0) AS matched_avg_charge_usd,
    SUM(total_charged_eur) / NULLIF(SUM(fx_covered_charge_count), 0) AS matched_avg_charge_eur
FROM dbo.FactTaxiDaily GROUP BY report_date ORDER BY report_date;
