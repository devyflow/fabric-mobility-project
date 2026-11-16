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

Load staged tables with explicit column lists using cross-database SQL or a Fabric Copy Pipeline. Check row counts, dimensions, and dollar totals against the Lakehouse before replacing the published reporting window. Then run `02_verify_star.sql`. These scripts are authored and still require live Warehouse execution. The SQL endpoint for the Lakehouse is a different item from the Warehouse.
