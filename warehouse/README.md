# Fabric Warehouse

Use the project Warehouse and run `01_create_star.sql`. The two facts have different grains. Connect each to DimDate and its own geography key; use a separate station-to-zone mapping for comparisons. Keep DimGDP at country/year and do not sum it by joining it onto every trip day.

| Warehouse table | Lakehouse input |
| --- | --- |
| DimDate | gold_dim_date |
| DimFX | gold_dim_fx |
| DimZone | gold_dim_zone, built from the TLC lookup plus an unknown zone record |
| DimGDP | silver_gdp, published to the reporting schema without its ingestion metadata |
| DimAirLocation | gold_dim_air_location |
| FactTaxiDaily | gold_fact_taxi_daily |
| FactAirQualityDaily | gold_fact_air_quality_daily |

Run `04_publish_from_lakehouse.sql` after notebook reconciliation. It uses explicit column lists and an explicit transaction to publish the configured reporting window. It blocks empty core facts, duplicate grains and missing references, compares counts and measures, and rolls back on failure. Run `02_verify_star.sql` and use `03_analysis.sql` for report queries. These scripts still require live Warehouse execution. The SQL endpoint for the Lakehouse is a different item from the Warehouse. The actual schema may be `dbo` or a configured Lakehouse schema; bind the identifiers to the deployed items before running.
