"""Run source checks locally. This does not create or replace Fabric Dataflows."""

import argparse
import csv
import io
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from .bronze import BronzeStore, utc_now, write_atomic
from .http import read_bytes

ROOT = Path(__file__).resolve().parents[2]


def get_world_bank(config, fetch=read_bytes):
    output = []
    pages = 1
    page = 1
    expected_total = None
    while page <= pages:
        query = urlencode({"format": "json", "date": f"{config['gdp_start_year']}:{config['gdp_end_year']}", "per_page": 1000, "page": page})
        url = f"https://api.worldbank.org/v2/country/{config['country']}/indicator/NY.GDP.MKTP.CD?{query}"
        raw = fetch(url)
        content = json.loads(raw)
        if not isinstance(content, list) or len(content) != 2 or not isinstance(content[0], dict):
            raise ValueError("Unexpected World Bank envelope")
        pages = int(content[0]["pages"])
        if pages > 100 or pages < 1 or int(content[0]["page"]) != page:
            raise ValueError("Invalid World Bank pagination metadata")
        expected_total = int(content[0]["total"])
        if not isinstance(content[1], list):
            raise ValueError("World Bank returned no record array")
        output.append((url, raw, content[1]))
        page += 1
    count = sum(len(part[2]) for part in output)
    if count != expected_total:
        raise ValueError("World Bank pagination is incomplete")
    return output


def get_openaq_locations(config, api_key, fetch=read_bytes):
    output = []
    previous = set()
    for page in range(1, 101):
        query = urlencode({"bbox": config["openaq_bbox"], "limit": 1000, "page": page})
        url = f"https://api.openaq.org/v3/locations?{query}"
        raw = fetch(url, headers={"X-API-Key": api_key})
        body = json.loads(raw)
        records = body.get("results")
        if not isinstance(records, list):
            raise ValueError("OpenAQ returned no results array")
        ids = [row["id"] for row in records]
        if len(set(ids)) != len(ids) or previous.intersection(ids):
            raise ValueError("OpenAQ pagination repeated a location; refusing a partial success")
        previous.update(ids)
        output.append((url, raw, records))
        if len(records) < 1000:
            return output
    raise ValueError("OpenAQ pagination exceeded safety bound")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/project.json")
    parser.add_argument("--download-taxi", action="store_true", help="Download the complete sample-month Parquet file")
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    date.fromisoformat(config["sample_month"] + "-01")
    if date.fromisoformat(config["sample_start"]) > date.fromisoformat(config["sample_end"]):
        raise ValueError("Sample dates are reversed")
    run_id = uuid.uuid4().hex
    store = BronzeStore(ROOT / "data/bronze")
    manifest, checks = [], []

    def preserve(source, url, raw, extension):
        record = store.save(source, raw, extension, url, run_id)
        manifest.append(record)
        return record

    def check(name, function):
        try:
            details = function()
            checks.append({"source": name, "status": "passed", **details})
        except Exception as error:
            # Error messages from network helpers contain no URL credentials/headers.
            checks.append({"source": name, "status": "failed", "error": str(error)})
        print(f"{name}: {checks[-1]['status']}", flush=True)

    def zones():
        url = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
        raw = read_bytes(url)
        preserve("taxi_zones", url, raw, "csv")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows or not {"LocationID", "Borough", "Zone", "service_zone"} <= set(rows[0]):
            raise ValueError("Unexpected taxi zone columns")
        if len({r["LocationID"] for r in rows}) != len(rows):
            raise ValueError("Duplicate zone IDs")
        return {"rows": len(rows), "columns": list(rows[0])}

    def gdp():
        parts = get_world_bank(config)
        rows = []
        for url, raw, records in parts:
            preserve("world_bank_gdp", url, raw, "json")
            rows.extend(records)
        return {"rows": len(rows), "pages": len(parts), "non_null_values": sum(r.get("value") is not None for r in rows), "years": [r["date"] for r in rows]}

    def ecb():
        fx_start = (date.fromisoformat(config["sample_start"]) - timedelta(days=7)).isoformat()
        query = urlencode({"format": "csvdata", "startPeriod": fx_start, "endPeriod": config["sample_end"]})
        url = f"https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?{query}"
        raw = read_bytes(url, headers={"Accept": "text/csv"})
        preserve("ecb_fx", url, raw, "csv")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        if not rows or not {"TIME_PERIOD", "OBS_VALUE", "CURRENCY", "CURRENCY_DENOM"} <= set(rows[0]):
            raise ValueError("Unexpected ECB response or no observations")
        if any(r["CURRENCY"] != "USD" or r["CURRENCY_DENOM"] != "EUR" for r in rows):
            raise ValueError("Unexpected exchange-rate direction")
        if len({r["TIME_PERIOD"] for r in rows}) != len(rows):
            raise ValueError("Duplicate ECB observation dates")
        return {"rows": len(rows), "rate_unit": "USD per EUR", "first_date": min(r["TIME_PERIOD"] for r in rows), "last_date": max(r["TIME_PERIOD"] for r in rows)}

    def taxi():
        url = f"https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{config['sample_month']}.parquet"
        headers = {} if args.download_taxi else {"Range": "bytes=0-3"}
        raw = read_bytes(url, headers=headers)
        if raw[:4] != b"PAR1":
            raise ValueError("Taxi response is not a Parquet file")
        if args.download_taxi:
            if len(raw) < 12 or raw[-4:] != b"PAR1":
                raise ValueError("Taxi download is truncated")
            entry = preserve("nyc_taxi", url, raw, "parquet")
            return {"bytes": len(raw), "bronze_path": entry["path"], "check": "downloaded; Parquet boundary markers verified; row profiling pending"}
        return {"check": "Parquet header verified only; full ingestion not performed"}

    def openaq(key):
        parts = get_openaq_locations(config, key)
        locations = []
        for url, raw, records in parts:
            preserve("openaq_locations", url, raw, "json")
            locations.extend(records)
        return {"locations": len(locations), "pages": len(parts), "check": "Location discovery only; sensor history and NYC membership still require verification"}

    check("taxi_zones", zones)
    check("world_bank_gdp", gdp)
    check("ecb_fx", ecb)
    check("nyc_taxi", taxi)
    key = os.environ.get("OPENAQ_API_KEY")
    if key:
        check("openaq", lambda: openaq(key))
    else:
        checks.append({"source": "openaq", "status": "blocked", "reason": "OPENAQ_API_KEY is not configured; no authenticated request was attempted"})
        print("openaq: blocked (API key not configured)", flush=True)
    store.write_manifest(run_id, manifest)
    report = {"run_id": run_id, "checked_at_utc": utc_now(), "scope": "Local source verification, not Fabric deployment", "checks": checks}
    write_atomic(ROOT / "reports/latest_preflight.json", json.dumps(report, indent=2).encode("utf-8"))
    lines = ["# Source verification", "", report["scope"], "", f"Checked at {report['checked_at_utc']}", "", "| Source | Status | Evidence |", "| --- | --- | --- |"]
    for row in checks:
        details = "; ".join(f"{k}: {v}" for k, v in row.items() if k not in ("source", "status"))
        lines.append(f"| {row['source']} | {row['status']} | {details.replace('|', '/')} |")
    write_atomic(ROOT / "reports/latest_preflight.md", ("\n".join(lines) + "\n").encode("utf-8"))
    return 1 if any(r["status"] == "failed" for r in checks) else 2 if any(r["status"] == "blocked" for r in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
