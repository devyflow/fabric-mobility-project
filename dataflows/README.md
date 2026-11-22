# Dataflows Gen2

These Power Query M queries are source-controlled authoring files, not deployed Dataflow items. Their syntax and scheduled execution must be verified in Fabric.

Create `df_world_bank_bronze` and `df_ecb_bronze`, use the Web API connector with Anonymous authentication, and paste the corresponding query into Advanced Editor. Add Lakehouse destinations `bronze_world_bank_pages` and `bronze_ecb_responses`. Select append for historical batches; do not replace earlier raw responses. Record each pipeline run ID and requested dates using Fabric parameters before scheduled use.

The result is a table containing the original response as text plus source metadata. This preserves the original JSON/CSV while meeting the requirement that Dataflows land tabular data. Silver parsing is a separate step. Repeated raw captures are acceptable; later processing must select/version batches explicitly rather than treating repeated captures as new business records.

The OpenAQ paging function in `openaq_hourly_pages.pq` is designed to save response pages in `bronze_openaq_hourly_pages`. Use `config/air_stations.json` for the reviewed station and sensor selections, then verify them through the API. The function needs a request function that supplies `X-API-Key` through a secure connection. If direct secure header binding is unavailable, verify a credential-backed endpoint or ask the instructor to approve a staging and Dataflow arrangement. The local API command reads `OPENAQ_API_KEY` from the process environment. The verified local report uses the separate public archive.

Tests still required in Fabric: scheduled refresh, parameter passing, destination append behavior, API pagination, failure propagation, and source-control export of the created items.
