"""Build and reconcile local reporting tables using real source files.

The DuckDB engine verifies business rules locally; it does not validate Fabric
capacity, Spark execution, Dataflow refresh, or Warehouse SQL compatibility.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from .bronze import BronzeStore, utc_now, write_atomic
from .http import read_bytes

ROOT = Path(__file__).resolve().parents[2]
GOLD_TABLES = ("dim_date", "dim_zone", "dim_fx", "dim_gdp", "fact_taxi_daily", "taxi_hourly", "mobility_daily")


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def find_inputs(cache):
    """Resolve the newest manifest's version per source, never union file globs."""
    selected = {}
    for manifest in sorted((cache / "_runs").glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name)):
        for record in json.loads(manifest.read_text(encoding="utf-8")):
            selected[record["source"]] = record
    required = {"nyc_taxi", "taxi_zones", "world_bank_gdp", "ecb_fx"}
    if required - selected.keys():
        raise ValueError(f"Missing cached sources: {sorted(required - selected.keys())}")
    result = {}
    for name in required:
        record = selected[name]
        path = (cache / record["path"]).resolve()
        if not path.is_relative_to(cache.resolve()):
            raise ValueError("Manifest path escapes cache")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}")
        result[name] = {**record, "local_path": path}
    return result


def load_references(con, inputs):
    zones = list(csv.DictReader(io.StringIO(inputs["taxi_zones"]["local_path"].read_text(encoding="utf-8-sig"))))
    keys = [int(row["LocationID"]) for row in zones]
    if not zones or len(set(keys)) != len(keys) or -1 in keys:
        raise ValueError("Invalid zone lookup keys")
    con.execute("CREATE OR REPLACE TABLE dim_zone(zone_id INTEGER, borough VARCHAR, zone_name VARCHAR, service_zone VARCHAR)")
    con.executemany("INSERT INTO dim_zone VALUES (?, ?, ?, ?)",
        [(int(row["LocationID"]), row["Borough"], row["Zone"], row["service_zone"]) for row in zones] + [(-1, "Unknown", "Unknown", None)])

    envelope, rows = json.loads(inputs["world_bank_gdp"]["local_path"].read_text(encoding="utf-8"))
    if int(envelope["pages"]) != 1 or int(envelope["total"]) != len(rows):
        raise ValueError("Local runner requires a complete single GDP page; use a date-bounded request")
    gdp = [(r["countryiso3code"], int(r["date"]), r["indicator"]["id"],
        Decimal(str(r["value"])) if r.get("value") is not None else None) for r in rows]
    if len({r[:3] for r in gdp}) != len(gdp) or not gdp:
        raise ValueError("GDP keys are empty or duplicated")
    con.execute("CREATE OR REPLACE TABLE dim_gdp(country_code VARCHAR, year INTEGER, indicator_code VARCHAR, gdp_current_usd DECIMAL(28,2))")
    con.executemany("INSERT INTO dim_gdp VALUES (?, ?, ?, ?)", gdp)

    rows = list(csv.DictReader(io.StringIO(inputs["ecb_fx"]["local_path"].read_text(encoding="utf-8-sig"))))
    rates, keys = [], set()
    for row in rows:
        if row["CURRENCY"] != "USD" or row["CURRENCY_DENOM"] != "EUR":
            raise ValueError("ECB quote direction must be USD per EUR")
        day = date.fromisoformat(row["TIME_PERIOD"])
        if day in keys:
            raise ValueError("Duplicate published FX date")
        keys.add(day)
        rate = Decimal(row["OBS_VALUE"]) if row.get("OBS_VALUE") else None
        valid = rate is not None and rate.is_finite() and rate > 0
        rates.append((day, rate if valid else None, valid, row.get("OBS_STATUS")))
    if not rates:
        raise ValueError("No FX observations")
    con.execute("CREATE OR REPLACE TABLE silver_fx(source_rate_date DATE, usd_per_eur DECIMAL(18,8), is_valid_rate BOOLEAN, observation_status VARCHAR)")
    con.executemany("INSERT INTO silver_fx VALUES (?, ?, ?, ?)", rates)


def build_tables(con, taxi_path, start, end, max_age=7):
    con.execute("CREATE OR REPLACE TABLE run_config(start_date DATE, end_date DATE, max_fx_age_days INTEGER)")
    con.execute("INSERT INTO run_config VALUES (?, ?, ?)", [start, end, max_age])
    con.execute(f"CREATE OR REPLACE VIEW source_taxi AS SELECT * FROM read_parquet({literal(taxi_path)}, filename=true, file_row_number=true)")
    con.execute((ROOT / "sql/local_taxi_silver.sql").read_text(encoding="utf-8"))
    con.execute((ROOT / "sql/local_gold.sql").read_text(encoding="utf-8"))


def verify(con):
    """Use independent totals and explicit grains rather than visual inspection."""
    one = lambda sql: con.execute(sql).fetchone()[0]
    source = one("SELECT count(*) FROM source_taxi")
    silver = one("SELECT count(*) FROM silver_taxi")
    in_window = one("SELECT count(*) FROM reporting_taxi")
    missing_date = one("SELECT count(*) FROM silver_taxi WHERE pickup_date IS NULL")
    outside = silver - in_window - missing_date
    if source != silver or min(in_window, missing_date, outside) < 0:
        raise AssertionError("Taxi row reconciliation failed")
    rules = {
        "daily_grain_unique": "SELECT count(*) FROM (SELECT report_date, pickup_zone_id FROM fact_taxi_daily GROUP BY ALL HAVING count(*) > 1)",
        "zone_keys_unique": "SELECT count(*) FROM (SELECT zone_id FROM dim_zone GROUP BY zone_id HAVING count(*) > 1)",
        "fx_keys_unique": "SELECT count(*) FROM (SELECT report_date, currency_pair FROM dim_fx GROUP BY ALL HAVING count(*) > 1)",
        "no_future_or_stale_rate": "SELECT count(*) FROM dim_fx WHERE source_rate_date > report_date OR rate_age_days > (SELECT max_fx_age_days FROM run_config)",
        "all_zones_resolve": "SELECT count(*) FROM fact_taxi_daily f LEFT JOIN dim_zone z ON f.pickup_zone_id=z.zone_id WHERE z.zone_id IS NULL",
        "all_dates_resolve": "SELECT count(*) FROM fact_taxi_daily f LEFT JOIN dim_date d USING(report_date) WHERE d.report_date IS NULL",
    }
    checks = [{"name": "source_rows_equal_silver_rows", "passed": source == silver}]
    for name, query in rules.items():
        bad = one(query)
        checks.append({"name": name, "passed": bad == 0, "exception_rows": bad})
    for table in ("fact_taxi_daily", "taxi_hourly"):
        actual = one(f"SELECT coalesce(sum(trip_count),0) FROM {table}")
        checks.append({"name": f"{table}_counts_equal_window", "passed": actual == in_window})
    for measure, source_field in (("base_fare_usd", "fare_usd"), ("total_charged_usd", "total_charged_usd")):
        expected = one(f"SELECT sum({source_field}) FROM reporting_taxi")
        actual = one(f"SELECT sum({measure}) FROM fact_taxi_daily")
        checks.append({"name": f"{measure}_reconciles_exactly", "passed": actual == expected,
                       "expected": str(expected), "actual": str(actual)})
    zero_source = one("SELECT count(*) FROM reporting_taxi WHERE distance_miles=0")
    zero_gold = one("SELECT coalesce(sum(zero_distance_trip_count),0) FROM fact_taxi_daily")
    checks.append({"name": "zero_distance_trips_retained", "passed": zero_source == zero_gold})
    failed = [row["name"] for row in checks if not row["passed"]]
    if failed:
        raise AssertionError(f"Validation failed: {failed}")
    return {"source_rows": source, "silver_rows": silver, "reporting_rows": in_window,
        "missing_pickup_date_rows": missing_date, "outside_reporting_window_rows": outside,
        "zero_distance_trips_in_window": zero_gold,
        "unknown_zone_trips": one("SELECT count(*) FROM reporting_taxi WHERE pickup_zone_id=-1"),
        "uncovered_fx_dates": one("SELECT count(*) FROM dim_fx WHERE usd_per_eur IS NULL"),
        "checks": checks}


def table_fingerprint(con, table):
    # Compare sorted serialized aggregate records rather than trusting row count alone.
    rows = con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
    return hashlib.sha256(json.dumps(rows, default=str, separators=(",", ":")).encode()).hexdigest()


def main(argv=None):
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="Path containing cached Bronze source directories and _runs")
    parser.add_argument("--workspace", type=Path, required=True, help="Scratch path for database and versioned builds")
    parser.add_argument("--start", default="2025-06-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--refresh-fx", action="store_true", help="Fetch full reporting window plus seven preceding days")
    parser.add_argument("--prove-rerun", action="store_true")
    args = parser.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end < start or (end - start).days > 3660:
        raise ValueError("Invalid reporting range")
    args.workspace.mkdir(parents=True, exist_ok=True)
    lock = args.workspace / "build.lock"
    handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(handle)
    run_id = uuid.uuid4().hex
    run_dir = args.workspace / "runs" / run_id
    run_dir.mkdir(parents=True)
    report = {"run_id": run_id, "started_at_utc": utc_now(), "scope": "Local verification; Fabric execution pending", "stages": []}
    report["duckdb_version"] = duckdb.__version__
    code_files = sorted((ROOT / "src/fabric_project").glob("*.py")) + sorted((ROOT / "sql").glob("*.sql"))
    report["transformation_source_sha256"] = {
        file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest() for file in code_files}
    con = None
    def stage(name, action):
        record = {"name": name, "started_at_utc": utc_now(), "status": "running"}
        report["stages"].append(record)
        write_atomic(run_dir / "run.json", json.dumps(report, indent=2).encode())
        try:
            result = action()
            record.update(status="passed", completed_at_utc=utc_now())
            print(f"{name}: passed", flush=True)
            return result
        except Exception:
            record.update(status="failed", completed_at_utc=utc_now())
            raise
    try:
        if args.refresh_fx:
            def refresh():
                query = urlencode({"format": "csvdata", "startPeriod": (start-timedelta(days=7)).isoformat(), "endPeriod": end.isoformat()})
                url = f"https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?{query}"
                raw = read_bytes(url, headers={"Accept": "text/csv"})
                rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                if not rows or any(r.get("CURRENCY") != "USD" or r.get("CURRENCY_DENOM") != "EUR" for r in rows):
                    raise ValueError("ECB response invalid; no manifest published")
                store = BronzeStore(args.cache)
                record = store.save("ecb_fx", raw, "csv", url, run_id)
                store.write_manifest(run_id, [record])
            stage("refresh_fx", refresh)
        inputs = stage("verify_input_checksums", lambda: find_inputs(args.cache))
        report["inputs"] = [{k: v for k, v in value.items() if k != "local_path"} for value in inputs.values()]
        report["reporting_start"], report["reporting_end"] = str(start), str(end)
        con = duckdb.connect(str(run_dir / "analytics.duckdb"))
        con.execute("SET threads = 2")
        con.execute("SET memory_limit = '1GB'")
        stage("load_references", lambda: load_references(con, inputs))
        stage("transform_taxi_silver_and_gold", lambda: build_tables(con, inputs["nyc_taxi"]["local_path"], start, end))
        report["validation"] = stage("reconcile", lambda: verify(con))
        from .local_air import build_air
        report["openaq"] = stage("check_air_capture", lambda: build_air(con, args.cache))
        published_tables = (*GOLD_TABLES, *report["openaq"]["tables"])
        before = {name: table_fingerprint(con, name) for name in published_tables}
        if args.prove_rerun:
            stage("rerun_same_inputs", lambda: build_tables(con, inputs["nyc_taxi"]["local_path"], start, end))
            if report["openaq"]["status"] == "passed":
                stage("rerun_air_capture", lambda: build_air(con, args.cache))
            after = {name: table_fingerprint(con, name) for name in published_tables}
            if before != after:
                raise AssertionError("Same-input rerun changed reporting tables")
            stage("reconcile_rerun", lambda: verify(con))
            report["same_input_rerun"] = "passed: sorted table fingerprints unchanged"
        report["table_fingerprints"] = before
        def export():
            for table in published_tables:
                con.execute(f"COPY (SELECT * FROM {table} ORDER BY ALL) TO {literal(run_dir / (table+'.csv'))} (HEADER, DELIMITER ',')")
            # Detailed Silver stays in the private scratch database; reporting CSVs are small.
            con.execute("CHECKPOINT")
        stage("export_reporting_tables", export)
        report["status"] = "passed_locally" if report["openaq"]["status"] == "passed" else "partial_success"
        report["completed_at_utc"] = utc_now()
        write_atomic(run_dir / "run.json", json.dumps(report, indent=2).encode())
        # Publish pointer only after complete successful stages. A failure never replaces it.
        write_atomic(args.workspace / "latest_success.json", json.dumps({"run_id": run_id, "path": f"runs/{run_id}"}, indent=2).encode())
        write_atomic(ROOT / "reports/local_build.json", json.dumps(report, indent=2).encode())
        print(f"Published verified local build {run_id}; OpenAQ: {report['openaq']['status']}", flush=True)
        return 0
    except Exception as error:
        report.update(status="failed", error=str(error), completed_at_utc=utc_now())
        write_atomic(run_dir / "run.json", json.dumps(report, indent=2).encode())
        raise
    finally:
        if con:
            con.close()
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
