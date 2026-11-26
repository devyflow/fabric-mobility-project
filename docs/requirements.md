# Requirement coverage

Source: the supplied Microsoft Fabric Data Engineering Project DOCX, supplemented by the supplied instructor screenshots. Status describes implementation evidence, not intent.

| Requirement | Component | Current status | Completion evidence |
| --- | --- | --- | --- |
| Fabric workspace and capacity | Fabric workspace | Signed in; Fabric Trial workspace type disabled at last check | Successful notebook run in capacity-backed workspace |
| Taxi monthly Parquet ingestion using Pipelines | `pl_taxi_bronze` | Local source checker built; Fabric pipeline pending | File in OneLake plus successful Copy activity |
| OpenAQ using Dataflow Gen2 | `df_openaq_bronze` | Actual historical observations verified using the public archive locally. M paging and five reviewed sensor IDs prepared. Authenticated refresh in Fabric pending | All requested pages and sensors captured in OneLake |
| World Bank using Dataflow Gen2 | `df_world_bank_bronze` | M source authored, not run in Fabric | Successful refresh and paginated source reconciliation |
| ECB using Dataflow Gen2 | `df_ecb_bronze` | M source authored, not run in Fabric | Successful refresh and correct rate direction |
| Raw Bronze in OneLake | `Files/bronze` and response tables | Local raw preservation built; cloud landing pending | Source responses and run IDs retained |
| Standardization and enrichment in PySpark | Silver notebooks | Notebook sources authored; corresponding taxi/economic business rules executed locally | Fabric notebook runs and field-level checks |
| Deduplication without silent loss | Partition replacement plus duplicate review | Local same-input rerun proves unchanged counts and table fingerprints; Spark rerun pending | Same-input rerun unchanged; all exclusions traceable |
| Cleaned Delta Silver | `silver_*` tables | Local Silver retains all 4,322,960 taxi rows; Fabric Delta write pending | Delta tables and count reconciliation |
| Gold aggregates in Lakehouse | `gold_*` tables | Local dates, zones, FX, GDP and both facts validated in two monthly runs. Lakehouse execution pending | Daily totals and weighted-average inputs reconcile |
| Warehouse star schema | Required facts and dimensions | DDL, transactional publish batch and verification SQL authored; live execution pending | Populated facts/dimensions with unique declared grains |
| FactTaxiDaily and FactAirQualityDaily | Warehouse facts | Schemas authored | No unintended row multiplication |
| DimDate, DimZone, DimFX, DimGDP | Warehouse dimensions | Schemas authored | Unique keys and valid reference relationships |
| Mobility visuals | Report/notebook | Actual June report and PNG charts generated; Fabric visualization notebook authored | Trips, fares, zones, time patterns |
| Air-quality visuals | Report/notebook | Actual PM2.5 and ozone trends and hourly coverage plotted for three reviewed stations | Pollutant-specific trends and coverage |
| Mobility/air-quality correlation | Report/notebook | True date and zone pairs in both periods, with a minimum observed-hour rule | Matched date/geography, sample count, limitations |
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

The local demonstration covers June 2025 and June 2024, with FX fetched from seven days before each window through month end. The same three stations have official taxi-zone assignments and observed PM2.5 or ozone. The comparison describes the observed months. A continuous historical or seasonal analysis requires additional overlapping data.

See the [report](../reports/project_report.html), [2025 evidence](../reports/local_build.json), [2024 evidence](../reports/comparison_build.json) and [implementation lesson](learn_project.md).

The Databricks implementation provides live PySpark, Delta, and on-demand job evidence for both captured months. Execution of the Fabric-specific items above is still pending. [Databricks workflow](../databricks/README.md), [verified workspace results](../reports/databricks_runs.json).
