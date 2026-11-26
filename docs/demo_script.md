# Project defense walkthrough

Run [the practice build](walkthrough.md) first. Bring your own notes on what happens to the $39 trip and how changing the monitor threshold changes the number of matched days. Use those results to explain your choices in your own words. This walkthrough takes about six minutes.

Before the defense, open the dashboard, the record trace, and the requirement checklist. Keep the local report for an offline demo. [Vercel dashboard](https://nyc-mobility-lakehouse.vercel.app), [record trace](../reports/trace_example.json), [requirement checklist](requirements.md), [offline report](../reports/project_report.html).

## 1. Show what the project answers

> This project combines NYC yellow taxi trips, air quality, exchange rates, and annual US GDP. Databricks builds the Delta tables for June 2024 and June 2025. Vercel displays the aggregates from those runs. OpenAQ provides PM2.5 and ozone. EPA AirData provides NO₂ at local monitoring stations.

Show the daily trips chart, then the same-month comparison. There were **3,539,142** in-window pickups in June 2024 and **4,322,940** in June 2025. That is an observed **22.1%** difference between the two months. The report covers those two snapshots.

In the pickup atlas, select **Manhattan**, **Jun 1** and **Seaport**. The map shows **409 pickups** for that zone and date in June 2025. **Copy map link** saves this selection for the defense. Reset the map to see the five-borough ranking. In **Daily trend**, turn on the June comparison or switch the measure to **Average base fare**. [Open the Seaport example](https://nyc-mobility-lakehouse.vercel.app/?month=2025-06&borough=Manhattan&day=2025-06-01&zone=209#atlas).

## 2. Follow one record through Bronze, Silver and Gold

Open the [record trace](../reports/trace_example.json). Start with `source_and_silver`, then show `gold_group`.

> Bronze holds the original file and a checksum I can use to verify its exact contents. This Seaport record reports zero miles, a $37.50 base fare and a $39 total charge. Silver adds a pickup date, a pickup hour and a zero-distance flag. The record still contributes one pickup and $39 to Gold. Its Gold row groups all 409 pickups in Seaport on June 1.

Point out what **one row** represents at each step. The project keeps **all 4,322,960** June 2025 source rows in Silver. Twenty have pickup dates outside June and remain visible there. The in-window trips include **134,896** zero-distance records.

## 3. Explain the two reporting joins

**Currency.** In the trace, open `chosen_fx`. ECB expressed its May 30 rate as **1.1339 dollars per euro**. The June 1 Seaport total of **$11,014.59** divided by that rate gives about **€9,713.90**. The rate is two days old. A seven-day maximum age prevents indefinite reuse. Show **$27.39** and **€23.79** on the June 2025 dashboard. Each total is divided by the same number of trips with both a charge and an exchange rate. The **$18.98 average base fare** uses the base-fare column and its own count. The GDP panel uses one national observation per year.

**Air and mobility.** Show `air_taxi_pair` and the PM2.5 chart. On June 1 the CCNY monitor averaged **3.4042 µg/m³** over 24 hourly observations. The Manhattanville taxi fact has **188 pickups** for the same date and zone. Aggregating each side before joining gives one paired point. A raw join of 188 trips with 24 readings could yield **4,512 rows** and inflate a later sum. The pair rule requires at least 18 observed hours per station-day.

Switch to NO₂ and select Queensboro Hill. In June 2025, the 28 matched days produce Pearson `r` of about **−0.41**. That means days with more pickups tended to have lower NO₂ in this sample. Weather, other traffic and local emissions can also influence the result. Open the hourly chart to show why the job also aligns each station reading to local pickup hour.

## 4. Prove the result can be rebuilt

Open the [June 2025 run evidence](../reports/local_build.json) and show `validation` and `same_input_rerun`.

> The source and Silver row counts match. The Gold counts and financial totals reconcile to the eligible Silver rows. A rebuild of each month from the same inputs produced the same fingerprints of the reporting tables. The test suite has 39 passing tests, including a recovery test that preserves the previous published run when a new evidence file cannot be written.

To demonstrate the Databricks implementation, open a successful run of `NYC Mobility | Verified Delta Snapshot`. Use `run_evidence` to identify the verified Delta schema, then use the [Seaport SQL example](../databricks/README.md#follow-a-result-in-databricks-sql) to find the $11,014.59 daily total. Point to the 20 June 2025 source rows with pickup dates outside the report window and show that Silver still contains all source rows.

Open the scheduled run evidence and locate `PERIODIC`, `SUCCESS`, and the matching table fingerprints. Explain that the run used verified files in Unity Catalog. The internet-facing collector can stage another source version. The recurring daily job is paused. Open the dashboard evidence to see the checked export and the nine reporting Delta tables. [Scheduled run evidence](../reports/refresh_evidence.json), [export evidence](../reports/dashboard_evidence.json).

## 5. Report your Fabric progress

Open the [requirement checklist](requirements.md). Show a [notebook](../notebooks/02_taxi_silver.ipynb) if asked what is ready for deployment.

> While troubleshooting Fabric access, I built and checked the workflow on real data in DuckDB and Databricks. The dashboard shows the verified Databricks output. The Fabric notebooks, Dataflow queries, Warehouse SQL and pipeline configuration are in Git. Running those Fabric components requires a capacity-backed workspace and an authenticated OpenAQ connection.

If time is limited, show the report, the $39 Seaport trace and the rerun result. Give the Fabric status in one sentence at the end.

## Questions to rehearse

| Likely question | Answer |
| --- | --- |
| Why keep zero-distance trips? | Distance and charge are independent source fields. The trace gives a concrete $39 charge that belongs in the reported total. |
| What does one row represent in each fact? | Taxi is one pickup date and zone. Air is one date, station, pollutant, and unit. The paired result matches zone and date within a pollutant series. |
| Why divide by 1.1339? | The rate is dollars per euro. Dollars divided by dollars per euro gives euros. |
| What happens if an input changes or a refresh fails? | A change produces a new checksum and source version. A failed run records the problem and preserves the previous success pointer. |
| What can you say about pollution? | Present the measured association, the matched day count and the locations covered. A causal claim would require a design that accounts for factors such as weather and other traffic. |
| Which parts of the assignment can you demonstrate today? | Show Bronze staging, PySpark and managed Delta, the scheduled replay, the report export and the Vercel dashboard. Then show the Fabric artifacts and the remaining workspace requirements. |
| How would you add weather? | Add its own ingestion step and preserve the raw response. Define the cleaned station and timestamp fields, then choose the Gold grouping and join keys before adding it to the report. |
