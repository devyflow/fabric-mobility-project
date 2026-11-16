# Implementation decisions

| Decision | Reason | Status or limitation |
| --- | --- | --- |
| Preserve raw bytes and checksums | Reproducibility and detection of revised source content | Implemented locally; OneLake version handling pending |
| Retain zero-distance trips | Instructor explicitly warns against silent dropping | Rule tested locally; Spark execution pending |
| Keep source and standardized fields | Parse errors remain auditable | Taxi notebook authored |
| Replace the selected source-month partition | Same-file reruns must not append another copy | Requires Fabric Delta execution and one-writer orchestration test |
| Flag identical rows without automatic deletion | Public taxi fields do not supply a proven globally unique trip ID | Final business-deduplication policy needs source profiling |
| Divide USD by USD-per-EUR | Correct ECB quote direction | Helper tested |
| Use preceding FX rate with a seven-day maximum age | Avoid look-ahead and unlimited stale-rate propagation | Proposed reporting policy, configurable; not an instructor-mandated threshold |
| GDP remains country/year | Daily joins must not sum national GDP repeatedly | Modeling pending |
| NYC sensor discovery before final dates | Prevent empty or misleading cross-domain comparisons | Blocked on OpenAQ key |
| One Lakehouse with named layers, plus Warehouse | Small solo-project layout while preserving all required layers | Proposed; cloud creation pending |
| No calendar-based execution plan | Build and verify the next dependency immediately | User preference |

## Initial governance policies

- Store public source data in Bronze without cleaning; retain all versions used in the submitted analysis.
- Do not commit API keys, tokens, raw data downloads, or local secret configuration.
- Limit workspace edit access to the project owner and course reviewers who actually need it; do not publish publicly by default.
- Include source URLs, retrieval times, requested ranges, and transformation versions in lineage evidence.
- Never replace missing data with zero merely to make a chart complete.
- Report failed loads and quality exclusions explicitly. Preserve records needed to explain every exclusion.
- Use clear UTC ingestion timestamps and a documented New York reporting-day convention.
- Validate data licensing/attribution for the selected OpenAQ providers before final publication.
- Keep cloud retention, role assignment, and scheduled-job enforcement marked pending until configured and demonstrated.

## Source references

- [TLC trip records and data dictionaries](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)
- [OpenAQ API key](https://docs.openaq.org/using-the-api/api-key)
- [OpenAQ pagination](https://docs.openaq.org/using-the-api/pagination)
- [OpenAQ location API](https://docs.openaq.org/api/operations/locations_get_v3_locations_get)
- [World Bank GDP source](https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json)
- [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)
