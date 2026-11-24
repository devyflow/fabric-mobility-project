# Build the project yourself on a small slice

You are building tables that answer questions about taxi pickups and charges. Start with one original taxi row. Work up to two zones, then add the exchange rate and an air monitor. Each step ends with a number you can reproduce.

## Open the practice database

Open PowerShell in the project folder. This machine already has the Python dependencies and the captured June 2025 data.

```powershell
$env:PYTHONPATH = '../../work/analytics_runtime'
python -X utf8 -i tools/practice_build.py --cache ../../work/fabric-source-cache/bronze
```

Wait for `>>>`. Paste the Python blocks below **one at a time into that same prompt**. The practice database lives in memory, so you can start fresh by typing `exit()` and running the command again. On another machine, follow [local setup](run_locally.md) and point `--cache` at the June 2025 Bronze directory.

## 1. Open the original file and look at one trip

```python
sql("""
    SELECT file_row_number, tpep_pickup_datetime, PULocationID,
           trip_distance, fare_amount, total_amount
    FROM taxi_file
    WHERE file_row_number = 158
""")
```

You should see **zone 209, 0.0 miles, $37.50 base fare and $39.00 total charged**. This is row 158 counting from zero in TLC's original June 2025 Parquet file. `taxi_file` is a view that reads the captured file. Parquet is the file format, and a view is a saved query you can use like a table.

The original ingest was done by [preflight.py](../src/fabric_project/preflight.py). [bronze.py](../src/fabric_project/bronze.py) preserved the bytes and added a manifest with the source URL and a SHA-256 checksum. A checksum changes when the file contents change. The practice loader verifies those bytes before letting you query them.

<details>
<summary>How to populate Bronze from an empty folder</summary>

Run these commands in PowerShell from the project root after installing the dependencies. The first downloads the June 2025 taxi file, zone lookup, World Bank GDP and ECB rates. The second captures the public OpenAQ archive for June and preserves the taxi-zone geometry used to assign monitors. Its date window includes any midnight-ending readings needed to complete June 30. This is the data acquisition step that created the practice inputs.

```powershell
$env:PYTHONPATH = 'src'
python -m fabric_project.preflight --month 2025-06 --cache data/practice/bronze --report-dir data/practice/preflight --download-taxi --skip-openaq-api
python -m fabric_project.openaq_archive --cache data/practice/bronze --start 2025-06-01 --end 2025-06-30
python -X utf8 -i tools/practice_build.py --cache data/practice/bronze
```

The commands print their checks and source counts. Look in `data/practice/bronze/_runs` for the manifests. When using the shared runtime on this machine, set `PYTHONPATH` to `src;../../work/analytics_runtime`.

</details>

## 2. Make Silver and test the zero-distance decision

Build a small practice input from the real file. Take June 1–7 and the two pickup zones used in the examples.

```python
sql("""
    CREATE TABLE source_taxi AS
    SELECT * FROM taxi_file
    WHERE tpep_pickup_datetime >= TIMESTAMP '2025-06-01'
      AND tpep_pickup_datetime < TIMESTAMP '2025-06-08'
      AND PULocationID IN (152, 209)
""")
sql("SELECT count(*) AS source_rows FROM source_taxi")
run_sql_file("local_taxi_silver.sql")
sql("""
    SELECT file_row_number, pickup_date, pickup_hour,
           fare_usd, total_charged_usd, quality_flags
    FROM silver_taxi
    WHERE file_row_number = 158
""")
```

There should be **4,238 source rows**. Open [the actual Silver SQL](../sql/local_taxi_silver.sql). `typed` adds new columns of consistent types. `enriched` extracts the date and hour from the pickup timestamp. The last `SELECT` adds the flags. For row 158, the new fields include hour **0** and the flag **`zero_distance`**.

Try the counterfactual. How much would a zero-distance filter drop?

```python
sql("""
    SELECT count(*) AS retained_rows,
           count(*) FILTER (WHERE distance_miles = 0) AS zero_distance_rows,
           sum(total_charged_usd) FILTER (WHERE distance_miles = 0) AS charges_on_those_rows
    FROM silver_taxi
""")
```

Expected **4,238 retained rows**, including **227 zero-distance records** with **$5,814.98** in total charges. Those are sample numbers. In this project zero distance is a flag, because the source gives evidence of what was charged even when the reported distance is zero. `NULL` means a field is missing. It is a different condition with its own check.

## 3. Build the lookup tables and the first Gold fact

Load the saved sources for zone names, FX, and GDP. Set the reporting dates and maximum age of an exchange rate. Then run the project's [Gold SQL](../sql/local_gold.sql).

```python
load_references(db, inputs)
sql("""
    CREATE TABLE run_config AS
    SELECT DATE '2025-06-01' AS start_date, DATE '2025-06-07' AS end_date,
           7 AS max_fx_age_days
""")
run_sql_file("local_gold.sql")
sql("""
    SELECT report_date, zone_name, trip_count, total_charged_usd, total_charged_eur
    FROM fact_taxi_daily
    JOIN dim_zone ON zone_id = pickup_zone_id
    WHERE report_date = DATE '2025-06-01' AND pickup_zone_id = 209
""")
sql("""
    SELECT report_date, source_rate_date, usd_per_eur, rate_age_days
    FROM dim_fx WHERE report_date = DATE '2025-06-01'
""")
```

On June 1, zone 209 is **Seaport** and has **409 pickups** with **$11,014.59** in recorded charges. Read the `GROUP BY pickup_date, pickup_zone_id` line in the SQL. That pair is the **grain** of this table. Grain means what one row represents. The $39 trip contributes one count and $39 to that one row.

June 1 was a Sunday. The rate comes from Friday May 30, **1.1339 USD per EUR**, two days earlier. Dividing the USD charge by 1.1339 gives about **€9,713.90**. Read the `LEFT JOIN silver_fx` and the ranking step in Gold SQL. They pick the latest valid rate on or before the date, up to seven days old. A missing rate leaves the EUR value empty and preserves the USD charge.

```python
sql("SELECT year, gdp_current_usd FROM dim_gdp ORDER BY year")
```

GDP is a country/year lookup for annual context. If you attached the annual amount to each daily row and summed it, you would count the same GDP many times.

## 4. Build the air fact and join it to the taxi fact

The air source is a captured OpenAQ archive file for each station and date. The code verifies the files and matches station coordinates to official TLC zone boundaries. It then averages hourly readings by date, station, pollutant, and unit. Run the real [local air module](../src/fabric_project/local_air.py).

```python
air = build_air(db, cache, min_hours=18)
sql("""
    SELECT report_date, location_id, pollutant_code,
           observed_hour_count, round(concentration_mean, 4) AS mean_pm25
    FROM fact_air_quality_daily
    WHERE report_date = DATE '2025-06-01' AND location_id = 384
      AND pollutant_code = 'pm25'
""")
sql("""
    SELECT report_date, pickup_zone_id, trip_count,
           round(concentration, 4) AS mean_pm25
    FROM matched_air_taxi
    WHERE report_date = DATE '2025-06-01'
      AND pickup_zone_id = 152 AND pollutant_code = 'pm25'
""")
```

Station 384 is **CCNY**. It had **24 observed hours** and a daily mean of **3.4042 µg/m³**. CCNY is in zone **152, Manhattanville**, where the taxi fact recorded **188 pickups** that day. Those values form one point in [the PM2.5 scatterplot](../reports/project_report.html).

Try to explain why the join uses the daily tables. Joining all 188 trips to all 24 readings could produce **4,512 rows** for one date and zone. The code first gives each side its intended grain, then matches on the shared date and zone within a pollutant and unit.

**Make a decision you can defend.** Change the monitor threshold from 18 observed hours to 24 in the practice database.

```python
print("Pairs with 18 hours:", air["matched_days_by_series"])
strict_air = build_air(db, cache, min_hours=24)
print("Pairs with 24 hours:", strict_air["matched_days_by_series"])
sql("""
    SELECT pickup_zone_id, pollutant_code, matched_days, round(pearson_r, 3) AS r
    FROM air_taxi_correlation ORDER BY pollutant_code
""")
```

Write down your two counts and pick the rule you would use for a follow-up. The expected pair counts are **14 at 18 hours** and **12 at 24 hours**. Requiring 24 hours improves day coverage and can remove usable dates. Eighteen keeps more days with some missing readings. Compare the sample sizes before interpreting Pearson's `r`, which summarizes how the paired values move together. The project report uses the same **18-hour** rule for both months.

## 5. Check that you can rebuild the same result

```python
audit = verify(db)
print(audit["source_rows"], audit["silver_rows"], audit["reporting_rows"])
before = table_fingerprint(db, "fact_taxi_daily")
run_sql_file("local_taxi_silver.sql")
run_sql_file("local_gold.sql")
print("Same Gold rows and values:", before == table_fingerprint(db, "fact_taxi_daily"))
```

Expected **4,238 4,238 4,238** and **`True`**. The first three counts match because this practice input already has a seven-day filter. The full June 2025 file has 20 rows with pickup dates outside June, which it keeps in Silver. The fingerprint check compares the sorted values as well as the row count. The full runner also checks air tables and publishes a success pointer only after checks and exports succeed.

For a concrete recovery example, read `test_failed_evidence_write_preserves_previous_success_pointer` in [test_local_build.py](../tests/test_local_build.py). It forces the final evidence write to fail and checks that the previous run remains the latest successful one.

## 6. Connect your practice rebuild to the full project

See the data points that would drive a trips-per-day chart for your two zones.

```python
sql("SELECT report_date, trip_count FROM mobility_daily ORDER BY report_date")
```

June 1 should total **597 pickups**, from 409 in Seaport and 188 in Manhattanville. The report generator does the same kind of `SELECT` over the full-month Gold table and sends the dates and counts to the chart. The full project rebuilds all zones for two June windows, checks both rebuilds and exports the reporting tables. [Report generator](../tools/render_local_report.py), [full local commands](run_locally.md).

| Part | Where to see it run locally | Fabric component prepared for the course |
| --- | --- | --- |
| Bring in the data | `preflight.py` and `openaq_archive.py` save the original bytes and manifest | The taxi Copy activity and the three API Dataflows land the data in OneLake. [Fabric setup](fabric_setup.md) |
| Inspect and prepare | `local_taxi_silver.sql`, `load_references`, and `local_air.py` add typed fields and checks | Notebooks 01–03 profile the taxis and prepare taxi and economic Silver tables. Notebook 05 prepares air Silver and Gold. [Notebook sources](../notebooks/source/) |
| Produce report tables | `local_gold.sql` groups taxis and builds date and FX tables. `local_air.py` builds the air fact and matches | Notebook 04 builds taxi, date, zone and FX Gold tables. Warehouse SQL defines and loads facts and dimensions for SQL reporting. [Warehouse scripts](../warehouse/) |
| Run in order and report | `local_build.py` logs each stage. `run_local_demo.py` runs both months. `render_local_report.py` reads the tables for the charts | The master pipeline specification describes the dependency order. Notebook 06 creates charts. Live Fabric deployment and scheduled execution are pending. [Pipeline specification](../pipelines/master.spec.json) |

To see the order the actual files were added, leave the Python prompt and run `git log --reverse --oneline`. The history shows the first Fabric source and modeling drafts, the local taxi build, the addition of verified OpenAQ archive data, and the changes from this review.

For the defense, choose a row and a chart you have walked through yourself. Explain what came in, the transformation you ran, why you used that rule, and the result you checked. Keep your own notes from the 18-hour and 24-hour comparison. Use facts you verified and describe any assistance accurately.
