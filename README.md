# NYC mobility and air quality

This project combines NYC yellow taxi trips, air monitoring, ECB exchange rates, and annual US GDP. Databricks processes June 2024 and June 2025 into Delta tables. Vercel serves the checked reporting aggregates. [Open the dashboard](https://nyc-mobility-lakehouse.vercel.app).

## What ran

- Bronze capture preserves source files and verifies their checksums. OpenAQ supplies observed PM2.5 and ozone. The selected OpenAQ stations lacked NO₂, so the dashboard uses EPA AQS for that pollutant. [OpenAQ archive](https://docs.openaq.org/aws/about), [EPA AirData](https://aqs.epa.gov/aqsweb/airdata/download_files.html).
- Databricks PySpark normalizes trip and currency fields, retains zero-distance records, and produces daily and hourly tables. The June 2025 build retained 4,322,960 source trips in Silver and reported 4,322,940 June pickups. [Databricks execution evidence](reports/databricks_runs.json).
- Lakeflow rebuilt the June 2025 Delta tables on a scheduled trigger and reproduced the validated fingerprints. The recurring daily schedule is paused. The source collector runs outside this trial workspace because its runtime could not reach several source hosts. [Scheduled run evidence](reports/refresh_evidence.json).
- The reporting job exports checked station and zone trends, taxi and air overlays, matched USD/EUR average charges, and two June periods of economic context. The public dashboard updates when a new export is deployed. [Dashboard export evidence](reports/dashboard_evidence.json).
- The interactive atlas maps 259 NYC taxi-zone IDs. Pick a borough or day, select a zone, and inspect the ranked pickup counts. The daily chart can compare the two Junes or select a map date. The fare converter uses the ECB rate for the selected pickup date. [Open the atlas](https://nyc-mobility-lakehouse.vercel.app/#atlas).

The course brief specifies Microsoft Fabric. The Fabric notebooks, Power Query sources, pipeline specification, and Warehouse SQL are prepared for that platform. Their Fabric runs still require a capacity-backed workspace. [Word brief coverage](docs/requirements.md).

## Start here

1. [Rebuild the tables yourself on a sample](docs/walkthrough.md). Start with one original taxi row, then run the real SQL and change a reporting rule in a scratch database.
2. Open the deployed dashboard and follow the defense walkthrough. The local report is available offline. [Vercel dashboard](https://nyc-mobility-lakehouse.vercel.app), [defense walkthrough](docs/demo_script.md), [local report](reports/project_report.html).
3. Rebuild the snapshots in Databricks or locally. [Databricks workflow](databricks/README.md), [local reproduction](docs/run_locally.md).
4. Inspect the two local build records and the cloud export that powers the dashboard. [June 2025 build](reports/local_build.json), [June 2024 build](reports/comparison_build.json), [Databricks dashboard export](reports/dashboard_evidence.json).

## Run the local checks

For the analytics build and tests, install the versions in `requirements-local.txt`. From this project directory in PowerShell, use the same Python to install and run them.

```powershell
python -m pip install -r requirements-local.txt
python tools/run_local_demo.py
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

The local demo uses the public archive. To check authenticated OpenAQ location discovery, run the masked PowerShell prompt. It writes its report under `data/openaq-check/`. Instructions for capturing hourly data through the API are in the local setup guide. [Authenticated capture](docs/run_locally.md#try-the-separate-authenticated-openaq-path).

```powershell
$env:PYTHONPATH = 'src'
$openaqSecret = Read-Host 'OpenAQ API key' -AsSecureString
$openaqPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($openaqSecret)
try {
    $env:OPENAQ_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($openaqPointer)
    python -m fabric_project.preflight --cache data/openaq-check/bronze --report-dir data/openaq-check
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
| `databricks/` | Tested PySpark snapshots, Lakeflow settings, and dashboard publication |
| `site/` | Vercel dashboard and static build |
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

The attached course DOCX defines the required Fabric components. Instructor screenshots add Git and data-retention clarifications. Weather/time-series export and Great Expectations bots are extra-credit work after completion of the core.
