# NYC mobility on Databricks

[nyc_mobility.py](nyc_mobility.py) is an importable Databricks notebook. It reads a verified one-month snapshot, writes a new set of Delta tables, and compares the results against the project's DuckDB run. The [Fabric requirement checklist](../docs/requirements.md) tracks the course-specific pieces.

## Verified workspace results

Both months ran through the same Lakeflow Job on Databricks. The job reconciled against DuckDB, and Unity Catalog confirmed 16 managed Delta tables for each successful snapshot. The taxi daily, air daily, and paired taxi–air tables also matched the local PySpark fingerprints in both months.

Independent June 2025 on-demand and scheduled reruns used the same inputs and reproduced all three reporting-table fingerprints. [On-demand run evidence](../reports/databricks_runs.json), [scheduled run evidence](../reports/refresh_evidence.json).

| Month | Taxi rows retained in Silver | Pickups inside the reporting month | Matched date, zone and pollutant rows |
| --- | ---: | ---: | ---: |
| June 2025 | 4,322,960 | 4,322,940 | 148 |
| June 2024 | 3,539,193 | 3,539,142 | 145 |

## Prepare the source files

The local project already captured June 2025 and June 2024. Use the raw cache and successful build workspace for the same month. The example uses the cache from this machine. From the project root:

```powershell
$env:PYTHONPATH = '../../work/analytics_runtime'
python tools/stage_databricks.py --cache ../../work/fabric-source-cache/bronze --build ../../work/defense-review/2025-06/builds --output ../../work/databricks-upload/2025-06
```

Use the existing output if the folder is already staged. On a different machine, install [local dependencies](../docs/run_locally.md) and use the cache and build paths from that run. The staging command checks the source bytes, keeps the original OpenAQ archive in a ZIP and exports the normalized hourly observations and reviewed station mapping from the verified local database. The destination has eight files, including `manifest.json` with SHA-256 checksums and independently verified comparison totals. The June 2024 cache on this machine is `../../work/june-2024-inputs`, and its workspace is `../../work/defense-review/2024-06/builds`.

## Run a snapshot

1. Create a managed Unity Catalog volume and upload the eight files into one month folder. Upload the prepared files because Free Edition and some trials restrict outbound internet access. [Databricks volume guide](https://docs.databricks.com/aws/en/volumes/volume-files), [Free Edition limits](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations).
2. In Workspace, import [nyc_mobility.py](nyc_mobility.py) as a Python source notebook and attach serverless compute. [Notebook import](https://docs.databricks.com/aws/en/notebooks/notebook-export-import).
3. Set `input_directory` to the folder containing `manifest.json` on the volume. For example, `/Volumes/workspace/nyc_mobility_inputs/bronze/2025-06`. Set `catalog` to a Unity Catalog catalog where you can create a schema. Run all cells.
4. After success, inspect the named output schema and its `run_evidence` Delta table. The run must reconcile the raw and Silver taxi counts, reporting date exclusions, flagged zero-distance counts, USD totals, FX coverage, and matched air/taxi observations. To reproduce the month, run it again against the same input folder and compare `reporting_table_sha256` in the two evidence rows.

The job creates a separate schema for each attempt. The evidence table is the completion marker. A failed attempt can leave intermediate tables in its schema while earlier successful schemas remain available.

The job template uses the same two parameters and allows one run at a time. Set the imported notebook path and input location, then pass the edited JSON to `databricks jobs create --json @path/to/job.json`. The 13:00 UTC daily schedule is paused after the verified scheduled run. To refresh staged data, point `input_directory` at the new version before running the job again. The trial connectivity check reached World Bank. It could not reach TLC, ECB, OpenAQ, or the NYC boundaries endpoint, so the collector uses a separate machine. [Lakeflow Job template](job.template.json), [Lakeflow Jobs configuration](https://docs.databricks.com/aws/en/jobs/configure-job), [job schedules](https://docs.databricks.com/aws/en/jobs/scheduled).

## Collect a new month

The collector fetches the sources for a published TLC month, checks the capture in DuckDB, and stages a new version. Supply `--volume-root` with an authenticated `--profile` to upload it. The manifest uploads last.

```powershell
python tools/prepare_databricks_month.py --month 2025-06 --work-dir data/refresh-demo
```

## Publish the dashboard

1. Download the hourly NO₂ archive for each year from EPA AirData. Run the staging tool with the archive, reporting month, and official NYC Taxi Zones GeoJSON. Upload each NYC slice, station mapping, and checksum manifest to its own volume folder. Retain the original national ZIP. [Staging tool](../tools/stage_epa_no2.py), [EPA AirData downloads](https://aqs.epa.gov/aqsweb/airdata/download_files.html), [NYC Taxi Zones](https://data.cityofnewyork.us/Transportation/NYC-Taxi-Zones/8meu-9t5y/data_preview).
2. Import the publication notebook. Run the exporter with the workspace path of that notebook and one `--snapshot CATALOG.SCHEMA=EPA_VOLUME_FOLDER` for each completed month. The notebook builds NO₂ Silver and air facts, then exports aggregates from the verified Delta snapshots. The exporter checks the result digest and confirms the reporting tables in Unity Catalog. [Publication notebook](publish_dashboard.py), [exporter](../tools/export_dashboard.py).
3. Run `node site/build.mjs` and deploy the configured Vercel project. The deployment uses aggregate files. Databricks credentials and source trip records stay in their original storage. [Vercel CLI deployment](https://vercel.com/docs/projects/deploy-from-cli).

EPA hours use source GMT fields to calculate New York reporting dates. Silver retains the measured value and qualifier. The aggregates use finite, nonnegative measurements. At sites with parallel instruments, the job chooses the instrument with the most valid distinct hours for that month. Station-days need at least 18 valid hours to enter a taxi comparison. [Dashboard publication evidence](../reports/dashboard_evidence.json).

## Follow a result in Databricks SQL

Replace `<run_schema>` with the schema printed by the successful notebook, including its catalog. For June 2025, check the Seaport total for June 1.

```sql
SELECT report_date, pickup_zone_id, trip_count, zero_distance_trip_count,
       total_charged_usd, total_charged_eur
FROM <run_schema>.fact_taxi_daily
WHERE report_date = DATE '2025-06-01' AND pickup_zone_id = 209;
```

The June 2025 local reference for that group is 409 pickups, 5 zero-distance records, and $11,014.59 in recorded charges. Then inspect a station-to-zone pair for the same date.

```sql
SELECT report_date, pickup_zone_id, trip_count, concentration, min_observed_hours
FROM <run_schema>.matched_air_taxi
WHERE report_date = DATE '2025-06-01' AND pickup_zone_id = 152 AND pollutant_code = 'pm25';
```

Zone 152 is Manhattanville. CCNY's 24 hours of observed PM2.5 are summarized once for the date and zone, alongside 188 taxi pickups. The two fact tables use different keys until the station data is grouped to the taxi zone.

## Explain the code at the defense

| Notebook section | What to explain |
| --- | --- |
| Load the manifest | The checksum confirms which input reached Databricks. The DuckDB totals are the expected values. Spark calculates them independently. |
| Taxi Silver | Parse the pickup time, type the amounts as decimals, and add quality flags. A zero-distance record still has a source charge. |
| Taxi Gold and FX | Group by date and pickup zone. Join one exchange rate per date and divide USD by USD per EUR. |
| Air and matched pairs | Reuse reviewed intervals and station-to-zone mappings from the local OpenAQ capture. Spark computes daily averages and joins by date and zone after the coverage check. |
| Validate | Compare the totals and check the unique reporting keys. Then write the run evidence and display the daily counts and correlation. |

The same Spark transformations can run locally with `tools/check_spark_snapshot.py` and PySpark 4.1.4. That command verifies the queries in the local Spark engine. The notebook exercises Unity Catalog and Delta writes when run in Databricks.

```powershell
$env:PYTHONPATH = '../../work/databricks-spark'
python tools/check_spark_snapshot.py ../../work/databricks-upload/2025-06 ../../work/databricks-upload/2024-06 --evidence ../../work/databricks-spark-checks.json
```
