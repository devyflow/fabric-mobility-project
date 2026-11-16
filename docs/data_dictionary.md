# Reporting data dictionary

This is the contract used by the authored notebooks and Warehouse scripts. Confirm data types and populated keys in the deployed project before submission.

| Table | Grain and source | Key measures or fields |
| --- | --- | --- |
| `silver_taxi_trips` | One retained TLC source record; month is source delivery metadata | `pickup_date` and `pickup_hour` in New York reporting time, `duration_seconds`, decimal `fare_usd` and `total_charged_usd`, `distance_miles`, `quality_flags`, `source_file`, and candidate duplicate count |
| `silver_gdp` | One World Bank country/year/indicator row | `gdp_current_usd` is nominal national GDP, nullable, not a city measure |
| `silver_fx` | One published date from ECB USD/EUR | `usd_per_eur`: USD units per euro; nullable when invalid. `observation_status` retains upstream status |
| `silver_air_hourly` | One distinguishable OpenAQ sensor/hour reading | UTC interval, NYC date/hour, original pollutant/concentration/unit, location, upstream flag, and eligibility |
| `DimDate` | One reporting date | Calendar year, month, day of week; Spark numbering starts Sunday at 1 |
| `DimZone` | One TLC zone ID, plus explicit unknown `-1` | Borough, zone name, and TLC service zone |
| `DimFX` | One reporting date/currency pair | Effective USD-per-EUR rate, actual source rate date, and age in days |
| `DimGDP` | One country/year/indicator | GDP current USD, kept separately from daily sums |
| `DimAirLocation` | One OpenAQ station | Name, WGS 84 latitude and longitude, optional verified TLC zone |
| `FactTaxiDaily` | One reporting date/pickup zone | Trips, zero-distance count, fare and charge totals, known-value denominators, currency coverage and matched totals |
| `FactAirQualityDaily` | One reporting date/station/pollutant/unit | Count of observed hours, sum of comparable hourly concentrations, daily mean |

Base fare and total charged are different TLC fields. Their known-value counts can differ. Use the correct denominator for an average. For USD/EUR comparisons use the USD charge total restricted to the same FX-covered trips as the EUR total.

Air measurements with different units remain separate. A rounded zone or day aggregate is not a substitute for actual station coverage. Hourly reporting retains UTC interval identity through daylight-saving changes. Missing coverage is shown as missing.
