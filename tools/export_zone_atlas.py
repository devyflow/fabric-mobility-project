"""Build the interactive zone map from reviewed boundaries and verified daily facts."""

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fabric_project.local_build import table_fingerprint


# An equirectangular display grid centered on New York. Measurements and joins use
# the original geographic coordinates in the ingestion pipeline.
GRID = {"west": -74.3, "north": 40.94, "latitude": 40.7, "units_per_degree": 10000}
NYC = {"Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"}


def display_ring(ring):
    points = []
    east_scale = GRID["units_per_degree"] * math.cos(math.radians(GRID["latitude"]))
    for lon, lat in ring[:-1]:
        point = [round((lon - GRID["west"]) * east_scale), round((GRID["north"] - lat) * GRID["units_per_degree"])]
        if not points or points[-1] != point:
            points.append(point)
    return points if len(points) >= 3 else []


def read_shapes(raw):
    outlines = {}
    for feature in json.loads(raw)["features"]:
        props = feature["properties"]
        if props["borough"] not in NYC:
            continue
        zone = int(props["locationid"])
        geometry = feature["geometry"]
        if geometry["type"] not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Expected NYC taxi zone polygons")
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = outlines.setdefault(zone, [])
        for outer, *holes in polygons:
            boundary = display_ring(outer)
            if boundary:
                rings.append(boundary)
                rings.extend(r for hole in holes if (r := display_ring(hole)))
    return outlines


def read_month(build, boundary_digest, snapshots):
    pointer = json.loads((build / "latest_success.json").read_bytes())
    run = (build / pointer["path"]).resolve()
    if not run.is_relative_to(build.resolve()):
        raise ValueError("Invalid build path in the successful-run record")
    report = json.loads((run / "run.json").read_bytes())
    if (report["status"] != "passed_locally" or report["run_id"] != pointer["run_id"]
            or report["openaq"]["boundaries"]["sha256"] != boundary_digest):
        raise ValueError("The selected build or boundary capture differs from its validation evidence")
    month = report["reporting_start"][:7]
    snapshot = snapshots[month]
    dates = [row["report_date"] for row in snapshot["days"]]
    offsets = {date: offset for offset, date in enumerate(dates)}
    with duckdb.connect(str(run / "analytics.duckdb"), read_only=True) as db:
        for table in ("fact_taxi_daily", "dim_zone"):
            if table_fingerprint(db, table) != report["table_fingerprints"][table]:
                raise ValueError(f"{month} {table} differs from the verified local build")
        zones = [(zone, name, borough) for zone, name, borough in db.execute(
            "SELECT zone_id, zone_name, borough FROM dim_zone ORDER BY zone_id"
        ).fetchall()]
        rows = db.execute("SELECT report_date, pickup_zone_id, trip_count FROM fact_taxi_daily").fetchall()

    counts = {zone: [0] * len(dates) for zone, _, _ in zones}
    for date, zone, trips in rows:
        counts[zone][offsets[date.isoformat()]] = trips

    for day, totals in enumerate(snapshot["days"]):
        if sum(series[day] for series in counts.values()) != totals["trips"]:
            raise ValueError(f"Atlas differs from the Databricks export on {dates[day]}")
    for top in snapshot["zones"]:
        if sum(counts[top["zone_id"]]) != top["trips"]:
            raise ValueError("Zone totals differ from the Databricks ranking")
    return month, zones, {"dates": dates, "pickups": counts}, report["openaq"]["boundaries"]["source_url"]


def export(builds, boundaries, dashboard, output):
    raw = boundaries.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    shapes = read_shapes(raw)
    snapshots = {s["month"]: s for s in json.loads(dashboard.read_bytes())["snapshots"]}
    periods, catalog = {}, None
    for build in builds:
        month, zones, period, source_url = read_month(build, digest, snapshots)
        if month in periods or (catalog is not None and catalog != zones):
            raise ValueError("Expected distinct months and consistent zone identifiers")
        periods[month], catalog = period, zones
    if set(periods) != set(snapshots):
        raise ValueError("Provide a validated build for each month in the dashboard")
    atlas = {
        "version": 1, "boundary_source": source_url, "boundary_sha256": digest, "grid": GRID,
        "zones": [{"id": zone, "name": name, "borough": borough, "rings": shapes.get(zone, [])}
                  for zone, name, borough in catalog],
        "months": periods,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=output.parent, delete=False) as file:
        json.dump(atlas, file, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        file.write("\n")
    os.replace(file.name, output)
    print(f"Exported {len(shapes)} mapped zone IDs and {len(periods)} reconciled months")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, action="append", required=True, help="Successful local build workspace")
    parser.add_argument("--boundaries", type=Path, required=True, help="Reviewed NYC Taxi Zones GeoJSON capture")
    parser.add_argument("--dashboard", type=Path, default=ROOT / "reports/dashboard.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/zone_atlas.json")
    args = parser.parse_args()
    export(args.build, args.boundaries, args.dashboard, args.output)
