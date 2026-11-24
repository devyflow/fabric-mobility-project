# Project defense walkthrough

Run [the practice build](walkthrough.md) first. Bring your own notes on what happens to the $39 trip and how changing the monitor threshold changes the number of matched days. Use those results to explain your choices in your own words. This walkthrough takes about six minutes.

Before the defense, open the [report](../reports/project_report.html), [record trace](../reports/trace_example.json), [June 2025 run evidence](../reports/local_build.json), and [requirement checklist](requirements.md). The report embeds its charts and opens from disk.

## 1. Show what the project answers

> My project combines NYC yellow taxi trips, air quality, exchange rates, and annual GDP. It shows where and when taxis were used, how the same charges look in dollars and euros, and how daily pickups and pollution varied together in monitored zones. This report comes from two verified local runs, June 2024 and June 2025.

Show the daily trips chart, then the same-month comparison. There were **3,539,142** in-window pickups in June 2024 and **4,322,940** in June 2025. That is an observed **22.1%** difference between the two months. The report covers those two snapshots.

## 2. Follow one record through Bronze, Silver and Gold

Open the [record trace](../reports/trace_example.json). Start with `source_and_silver`, then show `gold_group`.

> Bronze holds the original file and a checksum I can use to verify its exact contents. This Seaport record reports zero miles, a $37.50 base fare and a $39 total charge. Silver adds a pickup date, a pickup hour and a zero-distance flag. The record still contributes one pickup and $39 to Gold. Its Gold row groups all 409 pickups in Seaport on June 1.

Point out what **one row** represents at each step. The project keeps **all 4,322,960** June 2025 source rows in Silver. Twenty have pickup dates outside June and remain visible there. The in-window trips include **134,896** zero-distance records.

## 3. Explain the two reporting joins

**Currency.** In the trace, open `chosen_fx`. ECB expressed its May 30 rate as **1.1339 dollars per euro**. The June 1 Seaport total of **$11,014.59** divided by that rate gives about **€9,713.90**. The rate is two days old. A seven-day maximum age prevents indefinite reuse. The GDP panel displays one national observation per year.

**Air and mobility.** Show `air_taxi_pair` and the PM2.5 scatterplot. On June 1 the CCNY monitor averaged **3.4042 µg/m³** over 24 hourly observations. The Manhattanville taxi fact has **188 pickups** for the same date and zone. The daily aggregation gives one paired point. A raw join of 188 trips with 24 readings could yield **4,512 rows** and inflate a later sum. The pair rule requires at least 18 observed hours per station-day. Pearson's correlation summarizes the observed linear association within each series. The result covers three monitor locations and can reflect other conditions such as weather.

## 4. Prove the result can be rebuilt

Open the [June 2025 run evidence](../reports/local_build.json) and show `validation` and `same_input_rerun`.

> The source and Silver row counts match. The Gold counts and financial totals reconcile to the eligible Silver rows. A rebuild of each month from the same inputs produced the same fingerprints of the reporting tables. The test suite has 39 passing tests, including a recovery test that preserves the previous published run when a new evidence file cannot be written.

## 5. Report your Fabric progress

Open the [requirement checklist](requirements.md). Show a [notebook](../notebooks/02_taxi_silver.ipynb) if asked what is ready for deployment.

> While working on Fabric access, I continued building the processing, validation and reporting locally in DuckDB with real data. The six Fabric notebooks, Dataflow queries, Warehouse SQL and pipeline specification are prepared. A capacity-backed workspace and an authenticated OpenAQ Dataflow connection are needed to demonstrate ingestion into OneLake, PySpark and Delta execution, Warehouse publication, and scheduled refresh.

If time is limited, show the report, the $39 Seaport trace and the rerun result. Give the Fabric status in one sentence at the end.

## Questions to rehearse

| Likely question | Answer |
| --- | --- |
| Why keep zero-distance trips? | Distance and charge are independent source fields. The trace gives a concrete $39 charge that belongs in the reported total. |
| What does one row represent in each fact? | Taxi is one pickup date and zone. Air is one date, station, pollutant, and unit. The paired result matches zone and date within a pollutant series. |
| Why divide by 1.1339? | The rate is dollars per euro. Dollars divided by dollars per euro gives euros. |
| What happens if an input changes or a refresh fails? | A change produces a new checksum and source version. A failed run records the problem and preserves the previous success pointer. |
| What can you say about pollution? | Present the measured association, the matched day count and the locations covered. A causal claim would require a design that accounts for factors such as weather and other traffic. |
| Which parts of the assignment can you demonstrate today? | I can show the local source-to-report run, actual data and repeatability checks. I can show the authored Fabric components and explain their connections. Fabric runtime evidence remains pending. |
| How would you add weather? | Add its own ingestion step and preserve the raw response. Define the cleaned station and timestamp fields, then choose the Gold grouping and join keys before adding it to the report. |
