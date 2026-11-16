# Source verification

Local source verification, not Fabric deployment

Checked at 2026-11-16T05:08:48.719320+00:00

| Source | Status | Evidence |
| --- | --- | --- |
| taxi_zones | passed | rows: 265; columns: ['LocationID', 'Borough', 'Zone', 'service_zone'] |
| world_bank_gdp | passed | rows: 2; pages: 1; non_null_values: 2; years: ['2025', '2024'] |
| ecb_fx | passed | rows: 5; rate_unit: USD per EUR; first_date: 2025-06-02; last_date: 2025-06-06 |
| nyc_taxi | passed | bytes: 73542954; bronze_path: nyc_taxi/1bea7f5b09c744414451fa7fef09fbc5a393ffb1621c859be6ba0df23a14e1b6.parquet; check: downloaded; Parquet boundary markers verified; row profiling pending |
| openaq | blocked | reason: OPENAQ_API_KEY is not configured; no authenticated request was attempted |
