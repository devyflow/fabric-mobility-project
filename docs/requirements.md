# Coverage of the course brief

The supplied Word brief defines the original Microsoft Fabric requirements. The current submission runs on Databricks and includes a Vercel dashboard. The instructor screenshots add source control, extensibility, and explicit review of unusual trip records.

| Word requirement | Verified implementation | Fabric status |
| --- | --- | --- |
| Fabric workspace with Lakehouse and Warehouse | Live Databricks workspace, Unity Catalog volume, managed Delta facts and dimensions | Fabric workspace and capacity needed to execute there |
| TLC file Copy pipeline | Python collects and verifies the published Parquet and taxi zones. A Databricks job reads the checksummed copy from a volume. | Copy activity and OneLake path specified |
| OpenAQ, World Bank, ECB Dataflows Gen2 | Collector preserves the OpenAQ hourly public archive, GDP JSON and ECB quote CSV. The staged month includes their checksums. | Power Query M prepared. Authenticated Dataflow refresh is pending. |
| Raw Bronze in OneLake | Original Parquet, OpenAQ gzip payloads and geography, GDP JSON, and FX CSV staged in Unity Catalog. EPA national archives also have checksummed NYC slices. | OneLake load needs Fabric |
| PySpark Silver and Delta | Lakeflow types trips and economic data, retains all taxi records, and writes Silver Delta. OpenAQ normalization begins in the collector. EPA hourly Silver is built in Databricks. | Six source notebooks prepared |
| Deduplicate, normalize and enrich | OpenAQ keeps one exact reading per sensor and UTC hour and fails on conflicts. Aggregate keys are checked. TLC has no stable unique trip ID. Trips retain source identity, a local date/hour, and quality flags. | Native notebook execution pending |
| Gold aggregates and Warehouse star | Each snapshot contains the taxi daily fact plus date, zone, FX and GDP dimensions. Databricks also publishes station and zone daily air facts. | Fabric Warehouse DDL, publication, and verification SQL prepared |
| Mobility dashboard | Vercel shows trips/day, average base fare, zones, and pickup hour | Power BI is optional |
| Daily and location PM2.5 and NO₂ trends | OpenAQ PM2.5 and ozone at reviewed stations, plus NO₂ from EPA AQS at three NYC sites in 2025 and four in 2024 | EPA AQS supplements the reviewed OpenAQ sources |
| Taxi demand and air quality | Same-date, same-zone overlay and Pearson correlation with sample sizes. Hour profiles align by NYC local hour. | Databricks executes the reporting queries |
| USD/EUR and GDP | Average charges use the same FX-covered trips in both currencies. GDP stays at national, annual grain. | Databricks executes the reporting queries |
| Multi-year mobility and economic context | Two same-month June snapshots and the annual GDP for each year. The air comparison uses monitors common to both periods. | The two periods support an observed year-over-year comparison |
| Automated daily or hourly refresh | A scheduled Lakeflow run rebuilt the staged June 2025 inputs and matched the previous reporting fingerprints. The daily schedule is paused. Source capture and dashboard export run separately. | Fabric refresh pending |
| Data dictionary, lineage and governance | Repository documents grains, ownership, checksums, retention, publish validation, and extension steps. | Purview lineage and RLS are optional |
| Extend the solution | EPA NO₂ was added through a source adapter and joined at the existing reporting grains. The taxi snapshot and its validation stayed reusable. | Existing Fabric templates remain available |
| Source control and unusual trip values | The project source and sanitized output evidence are in Git. June 2025 retained 134,896 in-window zero-distance trips. | Fabric item export requires the Fabric workspace |

Weather export to a separate time-series database and a Great Expectations chat bot are separate-grade integrations listed in the instructor screenshots. The implemented submission focuses on core course requirements.

[Databricks snapshot evidence](../reports/databricks_runs.json), [scheduled run evidence](../reports/refresh_evidence.json), [dashboard export evidence](../reports/dashboard_evidence.json), [data dictionary](data_dictionary.md), [lineage and governance](lineage_and_governance.md), [Vercel dashboard](https://nyc-mobility-lakehouse.vercel.app).
