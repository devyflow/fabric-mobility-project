# Run and explain the verified local build

The local runner proves data processing and reporting rules while Fabric access is being resolved. Final course acceptance still requires Fabric Lakehouse/OneLake, Dataflows Gen2, Pipelines, PySpark execution, Warehouse, and an automated cloud run.

## Reproduce the local build

Use a Python virtual environment and install `requirements-local.txt`. Set `PYTHONPATH` to `src`. Run source verification first, then the build. Replace example paths with your scratch directories.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-local.txt
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python -m fabric_project.preflight --download-taxi
.\.venv\Scripts\python -m fabric_project.local_build --cache data/bronze --workspace data/local-build --refresh-fx --prove-rerun
.\.venv\Scripts\python tools/render_local_report.py --workspace data/local-build
.\.venv\Scripts\python -m unittest discover -s tests -v
```

The source checker exits with code 2 when OpenAQ is unconfigured. Review its per-source results: it may still have downloaded the three public sources successfully. A failed public source check must be resolved before running the build. `--refresh-fx` requests the reporting window plus seven preceding days to cover the first weekend.

During this session, large raw and working files were stored at `../../work/fabric-source-cache/bronze` and `../../work/local-analytics`, outside the user-facing output folder. The evidence and compact reporting outputs are in `reports/`. Future source checks use `data/bronze` by default; this path is excluded from Git.

The local runner selects one content version per source using manifest order, validates its checksum, and fails for unsupported multi-page GDP captures. Use a bounded GDP date range. The current runner validates one taxi source-month snapshot; do not claim it covers multiple years. Extend source selection to an explicit per-month manifest list before a historical multi-month run.

## Add actual OpenAQ data

Enter the API key through the masked prompt described in the README; do not paste it into chat, source files, or a committed parameter.

```powershell
python -m fabric_project.ingest_air --cache data/bronze --discover
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
python -m fabric_project.ingest_air --cache data/bronze --from-utc 2025-06-01T04:00:00Z --to-utc 2025-07-01T04:00:00Z
python -m fabric_project.local_build --cache data/bronze --workspace data/local-build --prove-rerun
python tools/render_local_report.py --workspace data/local-build
```

Ingestion windows must be timezone-aware and at most 32 days. June's UTC endpoints reflect New York daylight saving time. API boundary overlaps are resolved by UTC interval start; reporting date selection stays explicit. Captures with zero usable readings fail instead of producing an apparently complete environmental report.

The authenticated local capture verifies data availability and transformations. It does not replace the required Dataflow Gen2. That Dataflow still needs a secure header-credential mechanism and a tested scheduled refresh.

## Recovery and reruns

Each local run writes its own database, exports, stage timings, input checksums, and `run.json` in a unique scratch directory. Only after all requested stages validate does `latest_success.json` change. Failed runs preserve the previous success pointer. This behavior is covered by an integration test.

An exclusive `build.lock` prevents two local writers. If a process is killed and the lock survives, confirm that no build is still running before removing that specific lock file. Do not delete the old successful run to recover a failed one.

`--prove-rerun` rebuilds from the same inputs and compares deterministic sorted fingerprints of all published reporting tables. Expected result: no count or value changes. Failure stops publication.

## Explain the measured June result

All 4,322,960 source records survived local Silver processing. Of these, 4,322,940 have pickup dates inside June and 20 have dates outside June. The latter remain in Silver and are counted explicitly. All 134,896 zero-distance records inside the window remain in daily trip and financial aggregates.

The local reporting window contains $82,040,782.03 in recorded base fares and $118,393,342.44 in recorded total charges. Negative entries are retained. These values are source-record totals, not audited business revenue. All 30 reporting dates have an eligible preceding published FX rate. Refer to `reports/local_build.json` for exact reconciliation and source hashes.

One month supports a working demonstration, not seasonal or multi-year conclusions. Add overlapping taxi and sensor history after source coverage is verified.
