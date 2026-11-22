# Connect the first components to Fabric

## Access gate

Open https://app.fabric.microsoft.com/ and sign in with an eligible account. Confirm a workspace can use Fabric capacity or an available trial by creating a Lakehouse and running a notebook. A Power BI-only workspace is not sufficient. Trial access is not guaranteed. If unavailable, ask the course administrator for a capacity-backed workspace rather than assuming a paid purchase is needed.

On the last check, the account had a Power BI trial and **Fabric Trial** was disabled in the workspace form. A successfully activated Fabric capacity or an existing capacity-backed workspace is needed to run these components.

Create a dedicated project workspace, then `lh_mobility_environment` and `wh_mobility_environment`. A single Lakehouse with named layer areas is the current implementation choice, not an additional course requirement. Use its `Files/bronze` area for original files and `bronze_*`, `silver_*`, `gold_*` prefixes for tables. Attach it as the default Lakehouse for the notebooks.

## Taxi pipeline

Create `pl_taxi_bronze` with a string parameter `source_month`, initially `2025-06`.

1. Add Copy data, using an HTTP connection to `https://d37ci6vzurychx.cloudfront.net` with Anonymous authentication.
2. Set the relative URL using `@concat('trip-data/yellow_tripdata_', pipeline().parameters.source_month, '.parquet')`.
3. Select Binary copy to preserve the exact file, rather than rewriting source rows.
4. Set the Lakehouse Files destination folder using `@concat('bronze/nyc_taxi/source_month=', pipeline().parameters.source_month)`.
5. Set the filename using `@concat('yellow_tripdata_', pipeline().parameters.source_month, '.parquet')`.
6. Run for the sample month, then confirm the output file and inspect the run result.

This is the first-load setup. Before scheduled ingestion, add file identity/checkpoint handling and versioned storage for a changed upstream file. Do not silently overwrite the sole copy of a revised source. The local content-addressed store demonstrates the intended version-preservation behavior; it is not yet wired into Fabric orchestration.

Copy the zone lookup from `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv` into `Files/bronze/taxi_zones/`. This file will populate DimZone in a later increment.

## Notebooks

Import `notebooks/01_inspect_taxi_bronze.ipynb` and `notebooks/02_taxi_silver.ipynb` into Fabric. Attach the Lakehouse, use a PySpark environment, and run 01 before 02. Confirm that the source path matches the actual copied file.

Record actual counts and flags. Run 02 a second time and verify the selected partition count is unchanged. A notebook syntax check performed locally is not evidence that the Fabric runtime or Delta write succeeded.

## API Dataflows

Follow `dataflows/README.md` to create the two prepared Dataflows and configure their destinations. Verify a manual refresh before wiring them into a pipeline. Export created item definitions back into this repository so UI-created code is also tracked.

Then run notebook 03 for selected Bronze GDP and FX runs, followed by notebook 04 for taxi/date/FX Gold. Request ECB data beginning at least seven days before the first reporting date if you want to apply the preceding-rate policy at the window boundary.

The prepared default now covers 1–30 June 2025, with ECB requests beginning 25 May. Notebook first-code cells carry Fabric parameter tags; pass the master run ID and requested dates according to `pipelines/master.spec.json`. This specification still needs to be assembled and exported from the actual workspace.

The public archive supplied real historical observations locally. `config/air_stations.json` now contains five sensor IDs from that archive and verified zone mapping for three fixed stations. Test those selections and the requested intervals through the live OpenAQ API before deploying them. The required Dataflow still needs an API key, secure header binding and a verified refresh. Keep the key in a secure connection.

Notebook 05 expects `bronze_openaq_hourly_pages` and a `ref_air_sensor` table containing `sensor_id`, `location_id`, `station_name`, `latitude`, `longitude`, and nullable `zone_id`. Expand the reviewed station JSON to one row per sensor when creating the table. Notebook 05 publishes station/hour and station/day measures. Use `warehouse/README.md` for the remaining load and validation steps.

After both core facts validate, publish the Warehouse with `04_publish_from_lakehouse.sql`, run the Warehouse verification queries, then run notebook 06 using an actual pollutant/unit pair from the captured data. That notebook includes mobility, currency/GDP, air-quality coverage, and paired taxi/pollution analysis. Live execution must confirm the required Fabric runtime, Lakehouse schema, and connection behavior.

## Next completion gate

Taxi file lands, notebook 01 profiles it, notebook 02 writes a reconciled Silver partition and reruns without count inflation; the two public API Dataflows persist their raw responses. Capture actual run evidence before marking this gate complete.

## References

- [Fabric trials](https://learn.microsoft.com/en-us/fabric/get-started/fabric-trial)
- [HTTP Copy activity](https://learn.microsoft.com/en-us/fabric/data-factory/connector-http-copy-activity)
- [Web API connections for Dataflows](https://learn.microsoft.com/en-us/fabric/data-factory/connector-web)
- [Dataflow Git integration](https://learn.microsoft.com/en-us/fabric/data-factory/dataflow-gen2-cicd-and-git-integration)
