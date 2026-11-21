"""Discover OpenAQ station candidates or ingest reviewed sensors securely.

Use OPENAQ_API_KEY in the process environment. No keys are written to reports,
URLs, source configuration, or stored payload metadata.
"""
import argparse
import csv
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from .air_quality import fetch_hourly_pages
from .bronze import BronzeStore, utc_now, write_atomic
from .preflight import get_openaq_locations

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--stations", type=Path, default=ROOT / "config/air_stations.json")
    parser.add_argument("--from-utc", default="2025-06-01T04:00:00Z")
    parser.add_argument("--to-utc", default="2025-07-01T04:00:00Z")
    args = parser.parse_args(argv)
    key = os.environ.get("OPENAQ_API_KEY")
    if not key:
        print("Blocked: OPENAQ_API_KEY is not configured. No request sent.")
        return 2
    start = datetime.fromisoformat(args.from_utc.replace("Z", "+00:00"))
    end = datetime.fromisoformat(args.to_utc.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or not 0 < (end-start).total_seconds() <= 32*86400:
        raise ValueError("Use timezone-aware windows of at most 32 days")
    store, run_id = BronzeStore(args.cache), uuid.uuid4().hex
    records = []
    if args.discover:
        config = json.loads((ROOT / "config/project.json").read_text(encoding="utf-8"))
        candidates = []
        for url, raw, locations in get_openaq_locations(config, key):
            records.append(store.save("openaq_locations", raw, "json", url, run_id))
            for location in locations:
                for sensor in location.get("sensors", []):
                    parameter = sensor.get("parameter") or {}
                    coords = location.get("coordinates") or {}
                    candidates.append({"location_id": location["id"], "station_name": location.get("name"),
                        "sensor_id": sensor["id"], "pollutant": parameter.get("name"), "unit": parameter.get("units"),
                        "latitude": coords.get("latitude"), "longitude": coords.get("longitude"),
                        "timezone": location.get("timezone"), "is_mobile": location.get("isMobile"),
                        "geography_review": "pending", "zone_id": ""})
        output = io.StringIO()
        if candidates:
            writer = csv.DictWriter(output, fieldnames=candidates[0].keys())
            writer.writeheader()
            writer.writerows(candidates)
        write_atomic(ROOT / "reports/air_station_candidates.csv", output.getvalue().encode("utf-8"))
        store.write_manifest(run_id, records)
        print(f"Discovered {len(candidates)} sensor candidates; NYC membership/history still require review")
        return 0
    stations = json.loads(args.stations.read_text(encoding="utf-8"))
    if not isinstance(stations, list) or not stations:
        print("Blocked: no reviewed station/sensor mappings; run --discover first")
        return 2
    sensors = set()
    for station in stations:
        if station.get("geography_review") != "verified_nyc" or not station.get("geography_evidence"):
            raise ValueError("Station mapping requires NYC verification evidence")
        if station.get("is_mobile") is not False:
            raise ValueError("Use fixed stations for station/day comparisons")
        for sensor in station["sensor_ids"]:
            if sensor in sensors:
                raise ValueError("Duplicate sensor mapping")
            sensors.add(sensor)
            for url, raw, rows, page in fetch_hourly_pages(sensor, args.from_utc, args.to_utc, key):
                record = store.save("openaq_hourly", raw, "json", url, run_id)
                record.update(sensor_id=sensor, location_id=station["location_id"], page=page, result_count=len(rows))
                records.append(record)
                print(f"sensor {sensor}, page {page}: {len(rows)} rows", flush=True)
    store.write_manifest(run_id, records)
    write_atomic(args.cache / "openaq_latest.json", json.dumps({"run_id": run_id, "stations": stations,
        "requested_from_utc": args.from_utc, "requested_to_utc": args.to_utc,
        "completed_at_utc": utc_now(), "manifest": f"_runs/{run_id}.json"}, indent=2).encode())
    print("OpenAQ ingestion completed; raw pages retained and ready for validation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
