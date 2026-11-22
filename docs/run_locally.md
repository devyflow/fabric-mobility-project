# Run and explain the verified local build

The local runner proves data processing and reporting rules while Fabric access is being resolved. Final course acceptance still requires Fabric Lakehouse/OneLake, Dataflows Gen2, Pipelines, PySpark execution, Warehouse, and an automated cloud run.

## Reproduce the local build

Create a Python virtual environment and install the local dependencies. From the project root in PowerShell, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-local.txt
.\.venv\Scripts\python tools/run_local_demo.py
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The runner fetches the four public data domains and taxi-zone reference data for June 2025 and June 2024. For each month it uses the source checker, captures the OpenAQ archive, builds and reconciles the tables, and proves a same-input rerun. It renders the report after both months pass. Each period uses its own cache and workspace under `data/demo/`. Git ignores that directory. Plan for the taxi downloads and scratch databases to use disk space.

For a repeat run with the same downloaded inputs, use `--reuse-captures`. To reuse the caches already on this machine, run from the project root:

```powershell
.\.venv\Scripts\python tools/run_local_demo.py --reuse-captures `
  --primary-cache ../../work/fabric-source-cache/bronze `
  --comparison-cache ../../work/june-2024-inputs
```

Each build selects one content version per source from its Bronze manifests and verifies the checksums. It keeps each run-specific database and exports in scratch storage. The HTML, graphs, presentation trace and main evidence appear in `reports/`. The 2024 evidence has its own file. For a continuous multi-month analysis, build a version-selection plan for each requested taxi month before combining the Gold facts.

## Try the separate authenticated OpenAQ path

Enter the API key through the masked prompt described in the README; do not paste it into chat, source files, or a committed parameter.

Use a separate cache for this path so the local demonstration keeps its archive capture. The initial discovery is optional when reusing the five known sensor IDs in `config/air_stations.json`. Confirm coverage and source flag behavior with the live API. For new monitors, use discovery first and review the outputs.

```powershell
python -m fabric_project.ingest_air --cache data/api-bronze --discover
```

Review `reports/air_station_candidates.csv` against station coordinates, fixed/mobile status, pollutant/unit, history availability, and official NYC boundaries. The discovery bounding box includes nearby areas, so discovery alone is not NYC verification. Create a reviewed mapping in `config/air_stations.json` as an array of records with these fields:

| Field | Meaning |
| --- | --- |
| location_id | Actual OpenAQ station ID |
| station_name | Actual source station name |
| sensor_ids | List of actual associated sensor IDs |
| latitude and longitude | Actual station coordinates |
| is_mobile | Must be false for this fixed-station analysis |
| geography_review | `verified_nyc` only after boundary review |
| geography_evidence | Source/notes that support the boundary decision |
| zone_id | Verified TLC zone ID; null until mapped |

Do not enter invented example IDs. Then ingest and rerun:

```powershell
python -m fabric_project.preflight --month 2025-06 --cache data/api-bronze --report-dir data/api-preflight --download-taxi --skip-openaq-api
python -m fabric_project.ingest_air --cache data/api-bronze --from-utc 2025-06-01T04:00:00Z --to-utc 2025-07-01T04:00:00Z
python -m fabric_project.local_build --cache data/api-bronze --workspace data/api-build --report data/api-evidence.json --prove-rerun --require-air
```

Ingestion windows must be timezone-aware and at most 32 days. June's UTC endpoints reflect New York daylight saving time. API boundary overlaps are resolved by UTC interval start; reporting date selection stays explicit. Captures with zero usable readings fail instead of producing an apparently complete environmental report.

The authenticated capture can verify API availability and transformations. The assignment's Fabric Dataflow Gen2 still needs a secure header connection and a successful refresh.

## Recovery and reruns

Each local run writes its own database, exports, stage timings, input checksums, and `run.json` in a unique scratch directory. Only after all requested stages validate does `latest_success.json` change. Failed runs preserve the previous success pointer. This behavior is covered by an integration test.

An exclusive `build.lock` prevents two local writers. If a process is killed and the lock survives, confirm that no build is still running before removing that specific lock file. Do not delete the old successful run to recover a failed one.

`--prove-rerun` rebuilds from the same inputs and compares deterministic sorted fingerprints of all published reporting tables. Expected result: no count or value changes. Failure stops publication.

## Explain the measured June result

All 4,322,960 source records survived local Silver processing. Of these, 4,322,940 have pickup dates inside June and 20 have dates outside June. The latter remain in Silver and are counted explicitly. All 134,896 zero-distance records inside the window remain in daily trip and financial aggregates.

The local reporting window contains $82,040,782.03 in recorded base fares and $118,393,342.44 in recorded total charges. Negative entries are retained. These values are source-record totals, not audited business revenue. All 30 reporting dates have an eligible preceding published FX rate. Refer to `reports/local_build.json` for exact reconciliation and source hashes.

June 2025 includes 148 qualifying date-zone-pollutant matches across five series. June 2024 includes 145. The [comparison report](../reports/project_report.html) compares the matched June windows. The [lesson](learn_project.md) shows how the comparison was built.
