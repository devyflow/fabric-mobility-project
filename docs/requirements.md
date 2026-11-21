# Requirement coverage

Source: the supplied Microsoft Fabric Data Engineering Project DOCX, supplemented by the supplied instructor screenshots. Status describes implementation evidence, not intent.

| Requirement | Component | Current status | Completion evidence |
| --- | --- | --- | --- |
| Fabric workspace and capacity | Fabric workspace | Signed in; Fabric Trial workspace type disabled at last check | Successful notebook run in capacity-backed workspace |
| Taxi monthly Parquet ingestion using Pipelines | `pl_taxi_bronze` | Local source checker built; Fabric pipeline pending | File in OneLake plus successful Copy activity |
| OpenAQ using Dataflow Gen2 | `df_openaq_bronze` | M paging function and authenticated local ingestion CLI authored; credential binding and real discovery pending | All requested pages and sensors captured in OneLake |
| World Bank using Dataflow Gen2 | `df_world_bank_bronze` | M source authored, not run in Fabric | Successful refresh and paginated source reconciliation |
| ECB using Dataflow Gen2 | `df_ecb_bronze` | M source authored, not run in Fabric | Successful refresh and correct rate direction |
| Raw Bronze in OneLake | `Files/bronze` and response tables | Local raw preservation built; cloud landing pending | Source responses and run IDs retained |
| Standardization and enrichment in PySpark | Silver notebooks | Notebook sources authored; corresponding taxi/economic business rules executed locally | Fabric notebook runs and field-level checks |
| Deduplication without silent loss | Partition replacement plus duplicate review | Local same-input rerun proves unchanged counts and table fingerprints; Spark rerun pending | Same-input rerun unchanged; all exclusions traceable |
| Cleaned Delta Silver | `silver_*` tables | Local Silver retains all 4,322,960 taxi rows; Fabric Delta write pending | Delta tables and count reconciliation |
| Gold aggregates in Lakehouse | `gold_*` tables | Local date, zone, FX, GDP and taxi Gold validated; air aggregation tested with fixtures | Daily totals and weighted-average inputs reconcile |
| Warehouse star schema | Required facts and dimensions | DDL, transactional publish batch and verification SQL authored; live execution pending | Populated facts/dimensions with unique declared grains |
| FactTaxiDaily and FactAirQualityDaily | Warehouse facts | Schemas authored | No unintended row multiplication |
| DimDate, DimZone, DimFX, DimGDP | Warehouse dimensions | Schemas authored | Unique keys and valid reference relationships |
| Mobility visuals | Report/notebook | Actual June report and PNG charts generated; Fabric visualization notebook authored | Trips, fares, zones, time patterns |
| Air-quality visuals | Report/notebook | Plotting code authored; real observations pending | Pollutant-specific trends and coverage |
| Mobility/air-quality correlation | Report/notebook | Compatible-grain join and correlation code authored/tested with fixtures; actual pairs pending | Matched date/geography, sample count, limitations |
| USD/EUR and GDP context | Report/notebook | Real-data conversion and annual-context charts generated; all 30 June dates have eligible FX | Correct conversion and annual GDP treatment |
| Automated refresh | Master pipeline | Activity specification, run logs and recovery rules prepared; actual Fabric schedule pending | Recorded successful scheduled run |
| Data dictionary and lineage diagram | Documentation | Written and mapped to source, Silver, Gold and Warehouse contracts | Actual tables/fields mapped from sources to reports |
| Governance policies | Documentation | Access, secrets, retention, quality and recovery policies written; cloud enforcement pending | Access, secrets, retention, recovery procedures |
| Extensibility | Config and separate adapters | Initial config/adapters built | Add a source or period without rewriting existing adapters |
| All code in Git | Local repository | Implementation and reporting artifacts committed locally; Fabric item export pending | Clean Git status and source history |
| Zero-distance trips preserved | Silver taxi rules | 134,896 zero-distance records retained in real local June aggregates; Fabric execution pending | Zero-distance count retained after transformation |
| Power BI, Purview integration, RLS | Optional features | Deferred | Not required for core completion |
| Weather export and quality bot | Separate-grade integrations | Deferred | Only considered after core checks pass |

## Data scope

The local demonstration covers June 2025, with FX fetched from seven days before the reporting window through month end. It is a verified development scope, not proof of seasonal or multi-year conclusions. Choose overlapping taxi/OpenAQ history before final cross-domain reporting. The NYC bounding box is discovery-only and includes neighboring areas; station membership must be checked against boundaries.
