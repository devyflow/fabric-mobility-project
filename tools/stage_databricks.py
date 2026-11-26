"""Stage a verified source month for an offline upload to Databricks."""

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import duckdb


RAW_FILES = {
    "nyc_taxi": "yellow_taxi.parquet",
    "taxi_zones": "taxi_zones.csv",
    "ecb_fx": "ecb_fx.csv",
    "world_bank_gdp": "world_bank_gdp.json",
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def checksum(path):
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").hexdigest()


def verified_file(cache, entry):
    path = (cache / entry["path"]).resolve()
    if not path.is_relative_to(cache) or checksum(path) != entry["sha256"]:
        raise ValueError(f"Input differs from the verified capture: {entry['source']}")
    return path


def stage(cache, build, output):
    selection = read_json(build / "latest_success.json")
    run_dir = (build / selection["path"]).resolve()
    if not run_dir.is_relative_to(build) or output.exists():
        raise ValueError("Use a verified build directory and a new destination")
    run = read_json(run_dir / "run.json")
    air = run["openaq"]
    if run["run_id"] != selection["run_id"] or run["status"] != "passed_locally" or air["source_mode"] != "public_archive":
        raise ValueError("Use a successful local build with the OpenAQ public archive")
    month = date.fromisoformat(run["reporting_start"]).strftime("%Y-%m")
    archive_manifest = (cache / "_runs" / f"{air['run_id']}.json").resolve()
    if not archive_manifest.is_relative_to(cache):
        raise ValueError("Air manifest escaped the cache")
    originals = {entry["source"]: entry for entry in run["inputs"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-databricks-", dir=output.parent) as temp:
        staging = Path(temp) / "month"
        staging.mkdir()
        for name, filename in RAW_FILES.items():
            shutil.copyfile(verified_file(cache, originals[name]), staging / filename)

        # Keep the original archive and zone geometry alongside its normalized rows.
        with zipfile.ZipFile(staging / "openaq_originals.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(archive_manifest, "capture_manifest.json")
            for entry in read_json(archive_manifest):
                archive.write(verified_file(cache, entry), entry["path"])

        with duckdb.connect(str(run_dir / "analytics.duckdb"), read_only=True) as con:
            con.execute("""COPY (
                SELECT sensor_id, location_id, epoch(hour_start_utc)::BIGINT AS hour_start_epoch,
                       epoch(hour_end_utc)::BIGINT AS hour_end_epoch, pollutant_code, measurement_unit,
                       value, quality_flags, is_reportable, source_flagged
                FROM silver_air_hourly ORDER BY sensor_id, hour_start_utc
            ) TO ? (FORMAT JSON)""", [str(staging / "air_hourly.jsonl")])
            con.execute("""COPY (
                SELECT location_id, station_name, latitude, longitude, zone_id
                FROM dim_air_location ORDER BY location_id
            ) TO ? (FORMAT JSON)""", [str(staging / "air_locations.jsonl")])

        checked = run["validation"]
        totals = {row["name"]: row["actual"] for row in checked["checks"] if "actual" in row}
        manifest = {
            "month": month,
            "start_date": run["reporting_start"],
            "end_date": run["reporting_end"],
            "local_reference_run": run["run_id"],
            "openaq_capture_run": air["run_id"],
            "min_air_hours": air["min_hours_for_pair"],
            "files": {item.name: checksum(item) for item in sorted(staging.iterdir())},
            "expected": {
                **{key: checked[key] for key in (
                    "source_rows", "silver_rows", "reporting_rows", "outside_reporting_window_rows",
                    "missing_pickup_date_rows", "zero_distance_trips_in_window", "unknown_zone_trips", "uncovered_fx_dates",
                )},
                "base_fare_usd": totals["base_fare_usd_reconciles_exactly"],
                "total_charged_usd": totals["total_charged_usd_reconciles_exactly"],
                "air_silver_rows": air["silver_rows"],
                "rejected_air_rows": air["non_reportable_rows"],
                "matched_days_by_series": air["matched_days_by_series"],
            },
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staging.rename(output)
    print(f"Staged {month} in {output} ({len(manifest['files']) + 1} files)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="Original Bronze cache")
    parser.add_argument("--build", type=Path, required=True, help="Verified local workspace containing latest_success.json")
    parser.add_argument("--output", type=Path, required=True, help="New folder to upload")
    args = parser.parse_args()
    stage(args.cache.resolve(), args.build.resolve(), args.output.resolve())
