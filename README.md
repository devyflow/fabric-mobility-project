# Fabric mobility and environment project

This project combines NYC taxi trips, OpenAQ air quality, World Bank GDP, and ECB exchange rates in Microsoft Fabric. The build follows the supplied course DOCX and the instructor's clarifications about Git, extensibility, and preserving unusual data.

The local demonstration uses June 2025 and June 2024. Each month includes observed taxi, air-quality and exchange-rate data, with annual GDP for context.

## Current implementation

- A local source-verification command with original-response preservation, checksums, run manifests, explicit missing-key status, and bounded retries.
- Thirty-seven passing tests cover ingestion integrity, pagination, geography, air coverage and interval handling, zero-distance retention, FX conversion, SQL aggregation, reruns, failed publication, and concurrent-build rejection.
- Six importable Fabric notebooks for taxi profiling, Taxi Silver, economics Silver, taxi Gold, air quality Silver/Gold, and the four required analysis views. Python syntax checked; Fabric execution is pending.
- Power Query M sources for World Bank and ECB Bronze ingestion, plus an OpenAQ pagination function awaiting a credential-backed request. Fabric destinations, parameters, and scheduled execution are pending.
- Warehouse table definitions, a transactional Lakehouse-to-Warehouse publication batch, reconciliation SQL, and reporting queries. Live SQL execution is pending.
- A pipeline activity/dependency specification, tagged notebook parameter cells, recovery policy, data dictionary, and lineage/governance documentation.
- Two verified local builds with unchanged reporting-table fingerprints on rerun. The June 2025 build retained all 4,322,960 source taxi records in Silver and reported 4,322,940 in-window trips.
- Real OpenAQ PM2.5 and ozone data from three reviewed NYC stations. The local June 2025 correlation analysis produced 148 date, zone and pollutant pairs.
- A self-contained report, compact reporting CSVs, quality counts, and two traced examples for the project breakdown session.

All four data domains ran locally. OpenAQ used the [public data archive](https://docs.openaq.org/aws/about). The Fabric Trial workspace option was disabled at the last check. Live deployment, the authenticated OpenAQ Dataflow, and cloud validation remain pending. See [requirement coverage](docs/requirements.md).

## Start here

1. Open [the verified local report](reports/project_report.html) for charts and reconciliation.
2. Learn the implementation in [the step-by-step lesson](docs/learn_project.md), then rehearse with [the demo script](docs/demo_script.md).
3. Follow [local reproduction](docs/run_locally.md) or [Fabric setup](docs/fabric_setup.md) to run the components.
4. Inspect [the June 2025 build evidence](reports/local_build.json) and [the June 2024 comparison evidence](reports/comparison_build.json). The earlier source preflight report records a prior API access check.

## Run the local checks

For the analytics build and tests, install the versions in `requirements-local.txt`. From this project directory in PowerShell, use the same Python to install and run them.

```powershell
python -m pip install -r requirements-local.txt
python tools/run_local_demo.py
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

The local demo downloads the public archive without an API key. To verify the separate authenticated OpenAQ path, provide `OPENAQ_API_KEY` through a masked PowerShell prompt.

```powershell
$openaqSecret = Read-Host 'OpenAQ API key' -AsSecureString
$openaqPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($openaqSecret)
try {
    $env:OPENAQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($openaqPointer)
    python -m fabric_project.preflight
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($openaqPointer)
    Remove-Item Env:OPENAQ_API_KEY -ErrorAction SilentlyContinue
}
```

## Repository layout

| Location | Purpose |
| --- | --- |
| `config/project.json` | Non-secret source parameters and development dates |
| `src/fabric_project/` | Local source checks, raw persistence, and business-rule helpers |
| `tests/` | Behavior checks; no network calls or real credentials |
| `dataflows/` | Power Query M sources for Fabric Dataflows Gen2 |
| `notebooks/` | Importable notebooks with teaching notes |
| `notebooks/source/` | Readable, source-controlled notebook cell definitions |
| `tools/build_notebooks.py` | Rebuilds notebooks and checks Python syntax |
| `docs/` | Setup, explanation, decisions, and requirement coverage |
| `reports/` | Public-source verification evidence |
| `warehouse/` | Fabric Warehouse definitions, source-to-table mapping, and verification SQL |
| `sql/` | Locally executed DuckDB transformation SQL |
| `pipelines/` | Fabric master-pipeline specification and deployment checks |
| `data/` | Default location for future local raw downloads and manifests; excluded from Git |

## Source of truth

The attached course DOCX defines the required Fabric components. Instructor screenshots add Git and data-retention clarifications. The inventory/web-app examples are unrelated. Weather/time-series export and Great Expectations bots are extra-credit work after completion of the core.

## Completion rule

An authored notebook is not a deployed notebook. A source URL is not a successful ingestion. A table definition is not a validated dataset. Record actual results and keep pending work visible.
