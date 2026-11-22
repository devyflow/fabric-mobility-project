"""Ingest original OpenAQ public archive files for reviewed stationary monitors."""

import argparse
import csv
import gzip
import io
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from .air_quality import normalize_observation
from .bronze import BronzeStore, utc_now, write_atomic
from .http import read_bytes

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_ROOT = "https://openaq-data-archive.s3.amazonaws.com/"
ZONE_URL = "https://data.cityofnewyork.us/resource/8meu-9t5y.geojson?$limit=500"
OBJECT_PATTERN = re.compile(r"location-(\d+)-(\d{8})\.csv\.gz")
NYC_BOROUGHS = {"Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"}


def point_in_ring(x, y, ring):
    """Ray crossing with a separate boundary result to reject ambiguous zones."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        on_segment = (abs(cross) < 1e-13 and min(x1, x2) <= x <= max(x1, x2)
                      and min(y1, y2) <= y <= max(y1, y2))
        if on_segment:
            return None
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def locate_station(station, boundaries):
    x, y = station["longitude"], station["latitude"]
    matches = []
    for feature in boundaries["features"]:
        geometry = feature["geometry"]
        if geometry["type"] not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Expected polygon taxi-zone boundaries")
        polygons = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        for polygon in polygons:
            exterior = point_in_ring(x, y, polygon[0])
            if exterior is None:
                raise ValueError(f"Station {station['location_id']} lies on a zone boundary")
            if exterior:
                holes = [point_in_ring(x, y, ring) for ring in polygon[1:]]
                if None in holes:
                    raise ValueError(f"Station {station['location_id']} lies on a zone boundary")
                if not any(holes):
                    matches.append(feature["properties"])
    matches = {int(item["locationid"]): item for item in matches}
    if len(matches) != 1 or next(iter(matches.values()))["borough"] not in NYC_BOROUGHS:
        raise ValueError(f"Station {station['location_id']} needs a unique NYC taxi zone")
    zone_id, zone = next(iter(matches.items()))
    return {**station, "zone_id": zone_id, "zone_name": zone["zone"], "borough": zone["borough"],
            "geography_review": "verified_nyc", "geography_evidence": ZONE_URL, "is_mobile": False}


def archive_keys(location_id, start, last):
    first_month = start.replace(day=1)
    month = first_month
    prefix_base = f"records/csv.gz/locationid={location_id}"
    discovered = {}
    while month <= last:
        prefix = f"{prefix_base}/year={month.year}/month={month.month:02d}/"
        query = urlencode({"list-type": 2, "prefix": prefix})
        listing = ElementTree.fromstring(read_bytes(f"{ARCHIVE_ROOT}?{query}"))
        if listing.findtext("{*}IsTruncated") == "true":
            raise ValueError("Unexpected truncated monthly archive listing")
        for node in listing.findall(".//{*}Key"):
            key = node.text or ""
            match = OBJECT_PATTERN.fullmatch(key.rsplit("/", 1)[-1])
            if not key.startswith(prefix) or not match or int(match[1]) != location_id:
                raise ValueError("Unexpected archive object name")
            day = datetime.strptime(match[2], "%Y%m%d").date()
            if start <= day <= last:
                if day in discovered:
                    raise ValueError("Duplicate archive object date")
                discovered[day] = key
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return discovered


def parse_archive(payload, station):
    """The reviewed stations report hourly. OpenAQ timestamps denote interval ends."""
    reader = csv.DictReader(io.StringIO(gzip.decompress(payload).decode("utf-8-sig")))
    fields = set(reader.fieldnames or ())
    sensor_field = "sensors_id" if "sensors_id" in fields else "sensor_id"
    unit_field = "units" if "units" in fields else "unit"
    expected = {"location_id", sensor_field, "datetime", "lat", "lon", "parameter", unit_field, "value"}
    if expected - fields or station["frequency_minutes"] != 60:
        raise ValueError("Archive schema or station frequency differs from the expected contract")
    for row in reader:
        location_id = int(row["location_id"])
        if (location_id != station["location_id"]
                or abs(float(row["lat"]) - station["latitude"]) > 0.0002
                or abs(float(row["lon"]) - station["longitude"]) > 0.0002):
            raise ValueError(f"Archive station location differs from the reviewed mapping for {location_id}")
        end = datetime.fromisoformat(row["datetime"])
        if end.tzinfo is None or end.minute or end.second or end.microsecond:
            raise ValueError("Expected an offset-aware measurement ending at the top of the hour")
        end = end.astimezone(timezone.utc)
        start = end - timedelta(hours=1)
        value = float(row["value"]) if row["value"] else None
        observation = {"value": value,
            "period": {"datetimeFrom": {"utc": start.isoformat()}, "datetimeTo": {"utc": end.isoformat()}},
            "parameter": {"name": row["parameter"], "units": row[unit_field]}}
        # The archive exposes values and coordinates. Upstream flag state is unknown.
        yield normalize_observation(observation, int(row[sensor_field]), location_id, require_source_flag=False)


def capture(cache, start, end, stations_path, boundaries_path=None):
    if end < start or (end - start).days > 61:
        raise ValueError("Request an inclusive window of one to 62 days")
    locations = json.loads(stations_path.read_text(encoding="utf-8"))
    if not locations or len({s["location_id"] for s in locations}) != len(locations):
        raise ValueError("Supply distinct reviewed locations")
    store, run_id = BronzeStore(cache), uuid.uuid4().hex
    boundaries = boundaries_path.read_bytes() if boundaries_path else read_bytes(ZONE_URL)
    zone_polygons = json.loads(boundaries)
    stations = [locate_station(station, zone_polygons) for station in locations]
    zone_record = store.save("taxi_zone_boundaries", boundaries, "geojson", ZONE_URL, run_id)

    # Include the next day's object for any time-ending midnight observation.
    last = end + timedelta(days=1)
    days = {start + timedelta(days=i) for i in range((last - start).days + 1)}
    coverage = {}
    tasks = []
    for station in stations:
        location_id = station["location_id"]
        keys = archive_keys(location_id, start, last)
        if not keys:
            raise ValueError(f"No public archive objects for station {location_id}")
        coverage[str(location_id)] = {
            "zone_id": station["zone_id"], "zone_name": station["zone_name"], "dates_with_object": len(keys),
            "missing_object_dates": [str(day) for day in sorted(days - keys.keys())]}
        tasks.extend((station, day, key) for day, key in sorted(keys.items()))

    def download(task):
        station, day, key = task
        url = ARCHIVE_ROOT + quote(key, safe="/=")
        raw = read_bytes(url)
        count = sum(1 for _ in parse_archive(raw, station))
        entry = store.save("openaq_archive", raw, "csv.gz", url, run_id)
        return {**entry, "location_id": station["location_id"], "archive_date": str(day), "result_count": count}

    with ThreadPoolExecutor(max_workers=6) as pool:
        entries = list(pool.map(download, tasks))
    if any(not entry["result_count"] for entry in entries):
        raise ValueError("Archive returned an empty measurement file")
    store.write_manifest(run_id, [zone_record, *entries])
    info = {"run_id": run_id, "source_mode": "public_archive", "stations": stations,
        "start_date": str(start), "end_date": str(end), "archive_coverage": coverage,
        "completed_at_utc": utc_now(), "manifest": f"_runs/{run_id}.json"}
    write_atomic(cache / "openaq_latest.json", json.dumps(info, indent=2).encode())
    print(f"Captured {len(entries)} original OpenAQ files and {sum(e['result_count'] for e in entries):,} measurements")
    for station in stations:
        row = coverage[str(station["location_id"])]
        print(f"{station['station_name']} -> {station['zone_name']} ({station['zone_id']}), {row['dates_with_object']} dated files")
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 6, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 6, 30))
    parser.add_argument("--stations", type=Path, default=ROOT / "config/archive_stations.json")
    parser.add_argument("--boundaries-file", type=Path, help="Previously downloaded official NYC Taxi Zones GeoJSON")
    args = parser.parse_args()
    capture(args.cache, args.start, args.end, args.stations, args.boundaries_file)


if __name__ == "__main__":
    main()
