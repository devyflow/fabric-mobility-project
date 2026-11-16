# Requirement coverage

Source: the supplied Microsoft Fabric Data Engineering Project DOCX, supplemented by the supplied instructor screenshots. Status describes implementation evidence, not intent.

| Requirement | Component | Current status | Completion evidence |
| --- | --- | --- | --- |
| Fabric workspace and capacity | Fabric workspace | Signed in; Fabric Trial workspace type disabled at last check | Successful notebook run in capacity-backed workspace |
| Taxi monthly Parquet ingestion using Pipelines | `pl_taxi_bronze` | Local source checker built; Fabric pipeline pending | File in OneLake plus successful Copy activity |
| OpenAQ using Dataflow Gen2 | `df_openaq_bronze` | Paging function authored; credential binding and authenticated discovery pending | All requested pages and sensors captured in OneLake |
| World Bank using Dataflow Gen2 | `df_world_bank_bronze` | M source authored, not run in Fabric | Successful refresh and paginated source reconciliation |
| ECB using Dataflow Gen2 | `df_ecb_bronze` | M source authored, not run in Fabric | Successful refresh and correct rate direction |
| Raw Bronze in OneLake | `Files/bronze` and response tables | Local raw preservation built; cloud landing pending | Source responses and run IDs retained |
| Standardization and enrichment in PySpark | Silver notebooks | Taxi, GDP/FX and OpenAQ notebook sources authored | Fabric notebook runs and field-level checks |
| Deduplication without silent loss | Partition replacement plus duplicate review | Local payload idempotency tested; Spark rerun and business rules pending | Same-input rerun unchanged; all exclusions traceable |
| Cleaned Delta Silver | `silver_*` tables | Taxi write authored, not executed | Delta tables and count reconciliation |
| Gold aggregates in Lakehouse | `gold_*` tables | Taxi and air-quality notebook code authored; zone reference load pending | Daily totals and weighted-average inputs reconcile |
| Warehouse star schema | Required facts and dimensions | DDL and verification authored; live load pending | Populated facts/dimensions with unique declared grains |
| FactTaxiDaily and FactAirQualityDaily | Warehouse facts | Schemas authored | No unintended row multiplication |
| DimDate, DimZone, DimFX, DimGDP | Warehouse dimensions | Schemas authored | Unique keys and valid reference relationships |
| Mobility visuals | Report/notebook | Pending | Trips, fares, zones, time patterns |
| Air-quality visuals | Report/notebook | Pending | Pollutant-specific trends and coverage |
| Mobility/air-quality correlation | Report/notebook | Pending | Matched date/geography, sample count, limitations |
| USD/EUR and GDP context | Report/notebook | Formula helpers tested; visuals pending | Correct conversion and annual GDP treatment |
| Automated refresh | Master pipeline | Pending | Recorded successful scheduled run |
| Data dictionary and lineage diagram | Documentation | Initial architecture/decisions written; full dictionary pending | Actual tables/fields mapped from sources to reports |
| Governance policies | Documentation | Initial policies in decisions file; deployment enforcement pending | Access, secrets, retention, recovery procedures |
| Extensibility | Config and separate adapters | Initial config/adapters built | Add a source or period without rewriting existing adapters |
| All code in Git | Local repository | First increment tracked locally; Fabric item export pending | Clean Git status and source history |
| Zero-distance trips preserved | Silver taxi rules | Local rule tested; Fabric execution pending | Zero-distance count retained after transformation |
| Power BI, Purview integration, RLS | Optional features | Deferred | Not required for core completion |
| Weather export and quality bot | Separate-grade integrations | Deferred | Only considered after core checks pass |

## Data scope

June 2025 and a one-week FX request are development samples, not approved final scope. Before final reporting, choose overlapping taxi/OpenAQ dates and enough history to address seasonality and multi-year questions. The NYC bounding box is discovery-only and includes neighboring areas; station membership must be checked against boundaries.
