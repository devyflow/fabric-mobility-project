# Fabric mobility and environment project

This project combines NYC taxi trips, OpenAQ air quality, World Bank GDP, and ECB exchange rates in Microsoft Fabric. The build follows the supplied course DOCX and the instructor's clarifications about Git, extensibility, and preserving unusual data.

Work starts with executable source checks and small, explainable components. There is no calendar-based build schedule. Each component must pass its completion check before we rely on it.

## Current implementation

- A local source-verification command with original-response preservation, checksums, run manifests, explicit missing-key status, and bounded retries.
- Seventeen automated tests for ingestion integrity, pagination, retry behavior, zero-distance handling, and currency conversion.
- Five importable Fabric notebooks for taxi profiling, Taxi Silver, economics Silver, taxi Gold, and air quality Silver/Gold. Python syntax checked; Fabric execution is pending.
- Power Query M sources for World Bank and ECB Bronze ingestion, plus an OpenAQ pagination function awaiting a credential-backed request. Fabric destinations, parameters, and scheduled execution are pending.
- Warehouse table definitions and checks for duplicate keys, missing references, and matched USD/EUR averages.
- A setup guide, requirement checklist, and explanation notes for the project breakdown session.

The local source checks and real taxi profile ran successfully for TLC, World Bank, and ECB. OpenAQ still needs authenticated discovery and verified historical coverage. The Fabric Trial workspace option was disabled in the signed-in tenant when checked; live deployment, orchestration, visualization, and final validation remain pending. See [requirements](docs/requirements.md).

## Start here

1. Read [the walkthrough](docs/walkthrough.md) to understand the data journey.
2. Open [Fabric setup](docs/fabric_setup.md) to connect the prepared components.
3. Review [source verification results](reports/latest_preflight.md) for actual observations rather than assumed source availability.

## Run the local checks

Python 3.10 or newer; the core commands use only the standard library. From this project directory in PowerShell:

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
| `data/` | Default location for future local raw downloads and manifests; excluded from Git |

## Source of truth

The attached course DOCX defines the required Fabric components. Instructor screenshots add Git and data-retention clarifications. The inventory/web-app examples are unrelated. Weather/time-series export and Great Expectations bots are extra-credit work after completion of the core.

## Completion rule

An authored notebook is not a deployed notebook. A source URL is not a successful ingestion. A table definition is not a validated dataset. Record actual results and keep pending work visible.
