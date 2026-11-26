"""Stage the original NYC rows from an EPA AQS annual hourly NO2 download."""

import argparse
import csv
import hashlib
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from fabric_project.openaq_archive import locate_station


NYC_COUNTIES = {"005", "047", "061", "081", "085"}
FIELDS = (
    "State Code", "County Code", "Site Num", "Parameter Code", "POC",
    "Latitude", "Longitude", "Datum", "Parameter Name", "Date GMT",
    "Time GMT", "Sample Measurement", "Units of Measure", "Qualifier",
)


def checksum(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def stage(archive_path, boundaries_path, month, output):
    start = date.fromisoformat(f"{month}-01")
    next_month = (start + timedelta(days=31)).replace(day=1)
    source = f"https://aqs.epa.gov/aqsweb/airdata/hourly_42602_{start.year}.zip"
    boundaries = json.loads(boundaries_path.read_bytes())
    stations = {}
    selected = []

    with zipfile.ZipFile(archive_path) as archive:
        filename = f"hourly_42602_{start.year}.csv"
        with io.TextIOWrapper(archive.open(filename), encoding="utf-8-sig", newline="") as payload:
            reader = csv.DictReader(payload)
            if not set(FIELDS).issubset(reader.fieldnames or set()):
                raise ValueError("Unexpected EPA hourly export columns")
            for row in reader:
                if row["State Code"] != "36" or row["County Code"] not in NYC_COUNTIES:
                    continue
                if not str(start) <= row["Date GMT"] <= str(next_month):
                    continue
                if row["Parameter Code"] != "42602" or row["Units of Measure"] != "Parts per billion":
                    raise ValueError("Unexpected EPA parameter or measurement unit")
                code = f"36-{row['County Code']}-{row['Site Num']}"
                coordinates = (float(row["Latitude"]), float(row["Longitude"]))
                if stations.setdefault(code, coordinates) != coordinates:
                    raise ValueError(f"EPA site coordinates changed within the window: {code}")
                selected.append(row)

    if not selected:
        raise ValueError("No NYC NO2 observations in the archive window")

    mapped = []
    for code, (latitude, longitude) in sorted(stations.items()):
        location = locate_station({"location_id": code, "latitude": latitude, "longitude": longitude}, boundaries)
        mapped.append({"station_id": f"aqs:{code}", "station_name": f"{location['zone_name']} (AQS {code})",
                       "zone_id": location["zone_id"], "latitude": latitude, "longitude": longitude})

    output.mkdir(parents=True)
    with (output / "hourly.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    (output / "stations.json").write_text(json.dumps(mapped, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "month": month, "source": source, "annual_archive_sha256": checksum(archive_path),
        "nyc_slice_rows": len(selected), "nyc_site_count": len(stations),
        "boundaries_sha256": checksum(boundaries_path),
        "files": {name: checksum(output / name) for name in ("hourly.csv", "stations.json")},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{month}: {len(selected):,} original AQS rows across {len(stations)} NYC sites")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--boundaries", required=True, type=Path)
    parser.add_argument("--month", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    stage(args.archive, args.boundaries, args.month, args.output)
