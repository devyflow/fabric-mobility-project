"""Use authenticated OpenAQ pages when available; never create demo observations."""
import hashlib
import json

from .air_quality import deduplicate_observations, normalize_observation


def build_air(con, cache):
    pointer = cache / "openaq_latest.json"
    if not pointer.exists():
        return {"status": "blocked", "reason": "No completed authenticated OpenAQ capture", "tables": []}
    info = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = (cache / info["manifest"]).resolve()
    if not manifest_path.is_relative_to(cache.resolve()):
        raise ValueError("OpenAQ manifest path escapes cache")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stations = info["stations"]
    ids = [station["location_id"] for station in stations]
    if len(ids) != len(set(ids)):
        raise ValueError("Conflicting station mappings")
    records = []
    for entry in manifest:
        if entry["source"] != "openaq_hourly":
            continue
        path = (cache / entry["path"]).resolve()
        if not path.is_relative_to(cache.resolve()):
            raise ValueError("OpenAQ payload path escapes cache")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("OpenAQ payload checksum mismatch")
        body = json.loads(raw)
        if len(body["results"]) != entry["result_count"]:
            raise ValueError("OpenAQ page row count mismatch")
        records.extend(normalize_observation(row, entry["sensor_id"], entry["location_id"]) for row in body["results"])
    if not records:
        raise ValueError("Completed OpenAQ capture has no observations")
    clean, duplicate_count = deduplicate_observations(records)
    con.execute("""CREATE OR REPLACE TABLE silver_air_hourly(
        sensor_id INTEGER, location_id INTEGER, hour_start_utc TIMESTAMPTZ,
        hour_end_utc TIMESTAMPTZ, report_date DATE, report_hour INTEGER,
        pollutant_code VARCHAR, measurement_unit VARCHAR, value DOUBLE,
        quality_flags VARCHAR[], is_reportable BOOLEAN, source_flagged BOOLEAN)""")
    columns = [row[0] for row in con.execute("DESCRIBE silver_air_hourly").fetchall()]
    con.executemany("INSERT INTO silver_air_hourly VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [[row[c] for c in columns] for row in clean])
    con.execute("""CREATE OR REPLACE TABLE dim_air_location(location_id INTEGER,
      station_name VARCHAR, latitude DOUBLE, longitude DOUBLE, zone_id INTEGER)""")
    con.executemany("INSERT INTO dim_air_location VALUES (?,?,?,?,?)", [(
        station["location_id"], station["station_name"], station["latitude"], station["longitude"], station.get("zone_id")) for station in stations])
    con.execute("""CREATE OR REPLACE TABLE air_hourly AS
      SELECT a.report_date, a.report_hour, a.hour_start_utc, a.location_id,
        a.pollutant_code, a.measurement_unit, avg(a.value) AS concentration,
        count(*) AS sensor_count
      FROM silver_air_hourly a JOIN dim_date d USING(report_date)
      WHERE is_reportable
      GROUP BY a.report_date,a.report_hour,a.hour_start_utc,a.location_id,a.pollutant_code,a.measurement_unit;
      CREATE OR REPLACE TABLE fact_air_quality_daily AS
      SELECT report_date, location_id, pollutant_code, measurement_unit,
        count(*) AS observed_hour_count, sum(concentration) AS concentration_sum,
        avg(concentration) AS concentration_mean
      FROM air_hourly GROUP BY report_date, location_id, pollutant_code, measurement_unit;
      CREATE OR REPLACE TABLE matched_air_taxi AS
      WITH air AS (
        SELECT a.report_date,l.zone_id,a.pollutant_code,a.measurement_unit,
          avg(a.concentration_mean) AS concentration, count(*) AS station_count
        FROM fact_air_quality_daily a JOIN dim_air_location l USING(location_id)
        WHERE l.zone_id IS NOT NULL AND l.zone_id <> -1
        GROUP BY a.report_date,l.zone_id,a.pollutant_code,a.measurement_unit
      ) SELECT t.report_date,t.pickup_zone_id,t.trip_count,a.pollutant_code,
          a.measurement_unit,a.concentration,a.station_count
        FROM fact_taxi_daily t JOIN air a
          ON a.report_date=t.report_date AND a.zone_id=t.pickup_zone_id;
      CREATE OR REPLACE TABLE air_taxi_correlation AS
      SELECT pickup_zone_id,pollutant_code,measurement_unit,count(*) AS matched_days,
        corr(trip_count,concentration) AS pearson_r
      FROM matched_air_taxi GROUP BY pickup_zone_id,pollutant_code,measurement_unit""")
    daily_rows = con.execute("SELECT count(*) FROM fact_air_quality_daily").fetchone()[0]
    if not daily_rows:
        raise ValueError("No reportable OpenAQ observations match the reporting window")
    if con.execute("SELECT count(*) FROM fact_air_quality_daily WHERE observed_hour_count > 25").fetchone()[0]:
        raise ValueError("More observations than hours in a local calendar day")
    return {"status": "passed", "source_rows": len(records), "exact_duplicate_rows": duplicate_count,
        "silver_rows": len(clean), "non_reportable_rows": sum(not r["is_reportable"] for r in clean),
        "daily_rows": daily_rows, "run_id": info["run_id"],
        "tables": ["dim_air_location", "air_hourly", "fact_air_quality_daily", "matched_air_taxi", "air_taxi_correlation"]}
