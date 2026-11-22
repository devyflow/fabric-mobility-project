# Project breakdown script

This walkthrough takes about seven minutes. Explain the actual local build first, then show which Fabric deployment checks remain. Do not claim cloud execution until it has happened.

## Opening

"My project combines taxi activity, air quality and economic context. The required target is Microsoft Fabric, with Bronze, Silver and Gold layers, a Warehouse star schema, and automated refresh. While capacity access is being resolved, I built and tested the source processing and reporting locally."

Show `docs/requirements.md` and identify the pending Fabric deployment and authenticated Dataflow evidence.

## Show original evidence

"I downloaded the official June 2025 Yellow Taxi Parquet file. I retained the exact file, source URL, retrieval time and SHA-256 checksum. A revised source gets a new content version instead of silently replacing the evidence."

Open `reports/local_build.json` and point to the source checksum and input request parameters. Show World Bank annual JSON, ECB daily CSV, TLC monthly Parquet and the OpenAQ archive's dated gzip files. Different formats and frequencies explain the need for standardization.

## Follow one real row

Open `reports/trace_example.json`. Read the actual pickup timestamp, original zone, distance and fare. Show its typed Silver fields and `zero_distance` flag. Then point to its exact date/zone Gold group and chosen FX source date.

"The original row remains. I add fields that make reporting consistent. A flag tells me to investigate a value; it does not delete the trip. This row contributes one trip and its recorded amounts to the daily group."

Question: Why not remove zero-distance trips? Answer: the source contains positive charges for many such records, so automatic removal would change the financial totals without a justified business rule.

## Explain reconciliation

"The source has 4,322,960 records, and all survive in local Silver. June reporting contains 4,322,940 pickup records. The other 20 have dates outside June and remain in Silver. These counts reconcile exactly."

Open `reports/quality_summary.csv` to show actual flag counts. Explain that negative fare entries are retained and require interpretation. The retained June records sum to $82,040,782.03 in base fare and $118,393,342.44 in recorded total charges. These are different source measures and are not audited business revenue.

## Show the reporting model

"FactTaxiDaily has one row per reporting day and pickup zone. The air-quality fact has one row per day, monitoring station, pollutant and unit. If I joined every sensor reading to every trip, I could multiply taxi totals. I aggregate to compatible grains before comparison."

Open `warehouse/01_create_star.sql` or the data dictionary. Explain Date, Zone, FX and GDP dimensions. FX is daily; GDP remains annual national context.

## Show charts and currency logic

Open `reports/project_report.html`. Show daily trips, busiest pickup zones, pickup hours and average fare. Explain one measured observation without inferring why it happened.

"The ECB rate is USD per EUR, so EUR equals USD divided by the rate. Weekends use a preceding published rate, with a seven-day freshness limit. I record the source rate date, and all 30 June reporting dates are covered. The USD and EUR comparison uses the same eligible charge records."

If asked whether taxi activity drives GDP, explain that GDP gives annual national context. The taxi sample covers two month snapshots.

## Show the actual air match

"On June 1, the CCNY monitor in Manhattanville had 24 PM2.5 observations with a daily mean of 3.4042 micrograms per cubic meter. The daily taxi table reported 188 pickups in zone 152 on the same date. They form one point in the scatterplot. I used the official taxi-zone boundaries and required at least 18 observed hours per station-day to admit it to the join."

Find `air_station_day` and `air_taxi_pair` in `reports/trace_example.json`. In the report show the coverage chart and one matched series. Explain that Pearson r summarizes a linear association in the available pairs. June 2024 is a same-month comparison.

## Explain reliability and next evidence

"I reran the full local build against the same inputs. The sorted reporting-table fingerprints were unchanged, proving this build did not double-count the month. Tests also confirm that a failed build leaves the previous successful result intact."

Show `same_input_rerun` and the stage log in `reports/local_build.json`. Show the test result in `reports/test_results.txt`.

"I used real OpenAQ observations from its public archive to complete the local report. I prepared the six Fabric notebooks, the Dataflow queries, the Warehouse SQL, and the pipeline specification while resolving workspace access. Fabric deployment, authenticated refresh and scheduled execution are pending."

## Questions to rehearse

| Question | Answer to give |
| --- | --- |
| Why Bronze, Silver and Gold? | Original evidence, consistent detail, then reporting-ready aggregates. |
| What happens when the API fails? | Bounded transient retries, explicit failure, no downstream success checkpoint. Authentication errors fail immediately. |
| What happens on rerun? | The same selected month/window rebuilds its reporting outputs rather than appending duplicate trips. Source revisions keep their provenance. |
| What does one row represent? | State the grain of the particular source, Silver table or fact being discussed. |
| Why keep missing values? | Missing is different from zero. Explicit flags and denominators prevent invented measurements. |
| Why can two sensors not simply be averaged? | They need comparable pollutant, unit, interval and geography, with a stated weighting and coverage policy. |
| Does correlation show causation? | No. Seasonality, weather, coverage and other factors can affect both measurements. |
| How can weather be added? | Add an adapter, raw provenance, Silver contract, Gold grain and orchestration dependency without rewriting existing feeds. Implement extra-credit export only after the core is complete. |
