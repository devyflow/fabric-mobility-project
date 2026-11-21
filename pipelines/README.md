# Assemble and verify Fabric orchestration

`master.spec.json` is a precise activity/dependency specification, not an importable Fabric REST definition. Actual connection/item IDs are assigned by the workspace and must not be invented. Export the created Fabric items into Git after wiring and testing them.

Create source branches for the taxi Copy Pipeline, GDP Dataflow, ECB Dataflow, and OpenAQ Dataflow. Give all source captures the master run ID. Use date parameters and a bounded OpenAQ sensor/window set. Rebind each Dataflow's example literals to pipeline parameters in the actual Fabric editor before scheduled use.

The first code cell of every notebook is tagged `parameters` in the generated notebook. Notebook 02 accepts `sample_month`; 03 accepts `gdp_run_id` and `fx_run_id`; 04 accepts `start_date`, `end_date`, and `max_fx_age_days`; 05 accepts `run_id`, `start_date`, and `end_date`; 06 accepts a real `pollutant_code` and `measurement_unit`. The selected Lakehouse must be attached to each deployed notebook.

Use only successful source activity dependencies. Do not advance a watermark on partial ingestion or after an HTTP authentication error. Log source version, requested period, run ID, counts, status, duration, and error category. The first implementation uses full bounded snapshots; historical ingestion needs a per-month/per-sensor-window checkpoint table and version-aware late-data reprocessing.

After taxi and air Gold validate, run `warehouse/04_publish_from_lakehouse.sql` in the Warehouse. The script replaces the entire configured reporting window atomically and blocks if either core fact is empty. Wait for Lakehouse SQL endpoint synchronization; retry synchronization errors without rebuilding or deleting the previous Warehouse result. Run `02_verify_star.sql` and require all exception result sets to be empty and populated row counts to be nonzero. Only then refresh visualizations.

Before enabling a daily controller, demonstrate: a successful full run, same-input rerun, failed API request, failed transformation, missing environmental data, SQL endpoint synchronization delay, and recovery with the last successful report intact. Export actual run evidence and item definitions. A written specification is not proof that a schedule ran.
