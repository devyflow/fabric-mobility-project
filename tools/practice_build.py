"""Open a scratch database and verified June 2025 sources for docs/walkthrough.md."""
import argparse
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# These functions are available at the Python prompt for the walkthrough.
from fabric_project.local_air import build_air
from fabric_project.local_build import find_inputs, load_references, table_fingerprint, verify


def sql(query):
    # Finish any result left by a transformation that only needed one row.
    db.complete()
    result = db.sql(query)
    if result is not None:
        result.show(max_width=112)


def run_sql_file(name):
    path = ROOT / "sql" / name
    db.execute(path.read_text(encoding="utf-8"))
    print(f"Ran sql/{name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="The captured June 2025 Bronze directory")
    args = parser.parse_args()
    cache = args.cache.resolve()
    inputs = find_inputs(cache, "2025-06")
    source = inputs["nyc_taxi"]
    db = duckdb.connect()
    db.execute("SET threads = 1")
    db.execute("SET TimeZone = 'UTC'")
    db.read_parquet(str(source["local_path"]), filename=True, file_row_number=True).create_view("taxi_file")

    print("Verified the captured source files. Practice tables live in memory.")
    print(f"Taxi source  {source['source_url']}")
    print(f"SHA-256      {source['sha256']}")
    print('Try: sql("SELECT file_row_number, trip_distance, total_amount FROM taxi_file WHERE file_row_number = 158")')
