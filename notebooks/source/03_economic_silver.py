# CELL markdown
# # Prepare GDP and currency data
# Read one explicitly selected batch from each Bronze Dataflow table. Query
# responses remain in Bronze. Parse the current economic snapshot, keep null GDP
# observations visible, and validate keys before replacing the Silver snapshots.

# CELL code
gdp_run_id = "manual-development"  # Point at a single successful Dataflow run.
fx_run_id = "manual-development"

# CELL markdown
# ## Parse the two source formats
# These public feeds are small, so reading their response pages on the driver
# is simpler than distributing JSON envelope and CSV header parsing. Fail if
# the run contains ambiguous or incomplete source pages.

# CELL code
import csv
import io
import json
from datetime import date
from decimal import Decimal

def response_rows(table, run_id, columns):
    rows = (spark.table(table).where(F.col("run_id") == run_id)
            .select(*columns).distinct().limit(101).collect())
    if not 1 <= len(rows) <= 100:
        raise ValueError(f"{table}: missing or excessive responses for {run_id}")
    return rows

from pyspark.sql import functions as F

gdp_pages = response_rows("bronze_world_bank_pages", gdp_run_id, ["page", "pages", "payload_json"])
gdp_meta = {int(r.pages) for r in gdp_pages}
if len(gdp_meta) != 1 or sorted(int(r.page) for r in gdp_pages) != list(range(1, gdp_meta.pop() + 1)):
    raise ValueError("World Bank pages are incomplete or ambiguous")
gdp_values, gdp_seen, totals = [], set(), set()
for response in gdp_pages:
    meta, rows = json.loads(response.payload_json)
    if int(meta["page"]) != int(response.page):
        raise ValueError("World Bank payload and manifest disagree")
    totals.add(int(meta["total"]))
    for row in rows:
        key = (row["countryiso3code"], int(row["date"]), row["indicator"]["id"])
        if key in gdp_seen:
            raise ValueError(f"Duplicate GDP key: {key}")
        gdp_seen.add(key)
        value = row["value"]
        gdp_values.append((*key, Decimal(str(value)) if value is not None else None, gdp_run_id))
if totals != {len(gdp_values)}:
    raise ValueError("World Bank row count does not reconcile")

fx_responses = response_rows("bronze_ecb_responses", fx_run_id, ["payload_csv"])
fx_values, fx_seen = [], set()
for response in fx_responses:
    for row in csv.DictReader(io.StringIO(response.payload_csv.removeprefix("\ufeff"))):
        if row["CURRENCY"] != "USD" or row["CURRENCY_DENOM"] != "EUR":
            raise ValueError("Unexpected ECB currency direction")
        day = date.fromisoformat(row["TIME_PERIOD"])
        if day in fx_seen:
            raise ValueError(f"Duplicate ECB date: {day}")
        fx_seen.add(day)
        value = Decimal(row["OBS_VALUE"]) if row.get("OBS_VALUE") else None
        valid = value is not None and value.is_finite() and value > 0
        fx_values.append((day, value if valid else None, row.get("OBS_STATUS"), valid, fx_run_id))
if not fx_values:
    raise ValueError("ECB returned no observations")

# CELL markdown
# ## Write typed Silver tables
# GDP is annual and may be null. FX describes how many USD buy one EUR.
# Invalid observations retain their date and status so gaps can be explained.
# Currency rates are not filled here; Gold records the actual chosen source date.

# CELL code
gdp = spark.createDataFrame(gdp_values, "country_code string, year int, indicator_code string, gdp_current_usd decimal(28,2), source_run_id string")
fx = spark.createDataFrame(fx_values, "source_rate_date date, usd_per_eur decimal(18,8), observation_status string, is_valid_rate boolean, source_run_id string")
for name, frame, expected in (("silver_gdp", gdp, len(gdp_values)), ("silver_fx", fx, len(fx_values))):
    frame.write.format("delta").mode("overwrite").saveAsTable(name)
    actual = spark.table(name).count()
    assert actual == expected, f"{name} failed row reconciliation"
    print(f"{name}: {actual} records")
display(fx.orderBy("source_rate_date"))

# CELL markdown
# ## Explain it
# The source systems shape their data differently. I preserved their full
# responses, then parsed typed Silver rows. I compared page and row counts and
# ensured 2025 GDP could never be counted once per taxi day.
