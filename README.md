# Fabric mobility and environment project

This project combines NYC taxi trips, OpenAQ air quality, World Bank GDP, and ECB exchange rates in Microsoft Fabric. The build follows the supplied course DOCX and the instructor's clarifications about Git, extensibility, and preserving unusual data.

Work starts with executable source checks and small, explainable components. There is no calendar-based build schedule. Each component must pass its completion check before we rely on it.

## Current implementation

- A local source-verification command with original-response preservation, checksums, run manifests, explicit missing-key status, and bounded retries.
- Thirty-four passing tests covering ingestion integrity, pagination, retry behavior, zero-distance retention, FX conversion, air-quality interval handling, real SQL aggregation, reruns, failed publication, and concurrent-build rejection.
- Six importable Fabric notebooks for taxi profiling, Taxi Silver, economics Silver, taxi Gold, air quality Silver/Gold, and the four required analysis views. Python syntax checked; Fabric execution is pending.
- Power Query M sources for World Bank and ECB Bronze ingestion, plus an OpenAQ pagination function awaiting a credential-backed request. Fabric destinations, parameters, and scheduled execution are pending.
- Warehouse table definitions, a transactional Lakehouse-to-Warehouse publication batch, reconciliation SQL, and reporting queries. Live SQL execution is pending.
- A pipeline activity/dependency specification, tagged notebook parameter cells, recovery policy, data dictionary, and lineage/governance documentation.
- A verified local June build: all 4,322,960 source records retained in Silver, 4,322,940 inside June, 20 outside June explicitly accounted for, and unchanged reporting-table fingerprints on rerun.
- Real-data charts, a self-contained HTML report, compact reporting CSVs, quality counts, and a traced source-record example for your breakdown session.

TLC, World Bank, and ECB run locally. OpenAQ ingestion/aggregation code is implemented and tested with labelled synthetic fixtures; actual NYC observations, reviewed geography, and Dataflow credential binding remain pending. The Fabric Trial workspace option was disabled at the last check; live deployment and cloud validation remain pending. See [requirements](docs/requirements.md).

## Start here

1. Open [the verified local report](reports/project_report.html) for charts and reconciliation.
2. Use [the walkthrough](docs/walkthrough.md) and [the demo script](docs/demo_script.md) to explain the actual implementation.
3. Follow [local reproduction](docs/run_locally.md) or [Fabric setup](docs/fabric_setup.md) to run the components.
4. Inspect [the latest build evidence](reports/local_build.json); the earlier source preflight report is retained as historical evidence.

## Run the local checks

Source verification uses the standard library. The analytics build and its integration tests require the dependencies in `requirements-local.txt` (Python 3.10 or newer, subject to package wheel availability). From this project directory in PowerShell:

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python -m fabric_project.preflight
```

For the complete sample-month taxi download (can be tens of megabytes):

```powershell
python -m fabric_project.preflight --download-taxi
```

Exit codes: `0` all requested checks passed, `1` at least one failed, `2` a required source is blocked. A missing OpenAQ key is not success. Even a successful location discovery is not proof of historical sensor coverage.

To discover OpenAQ locations, supply `OPENAQ_API_KEY` through the process environment without pasting it into chat, committing it, or typing it as a literal into shell history. For example, enter it through a masked PowerShell prompt:

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
