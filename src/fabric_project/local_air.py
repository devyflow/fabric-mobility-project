"""Process checked OpenAQ API pages or original public archive files."""
import hashlib
import json

from .air_quality import deduplicate_observations, normalize_observation
from .openaq_archive import locate_station, parse_archive


def verified_payload(cache, entry):
    path = (cache / entry["path"]).resolve()
    if not path.is_relative_to(cache.resolve()):
        raise ValueError("OpenAQ payload path escapes cache")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"Checksum mismatch for {entry['source']}")
    return raw


def build_air(con, cache, min_hours=1):
    pointer = cache / "openaq_latest.json"
    if not pointer.exists():
        return {"status": "blocked", "reason": "No completed OpenAQ capture", "tables": []}
    info = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = (cache / info["manifest"]).resolve()
    if not manifest_path.is_relative_to(cache.resolve()):
        raise ValueError("OpenAQ manifest path escapes cache")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stations = info["stations"]
    ids = [station["location_id"] for station in stations]
    if len(ids) != len(set(ids)):
        raise ValueError("Conflicting station mappings")
    by_id = {station["location_id"]: station for station in stations}
    mode = info.get("source_mode", "authenticated_api")
    if mode not in {"authenticated_api", "public_archive"}:
        raise ValueError("Unknown OpenAQ capture mode")
    zone_evidence = None
    if mode == "public_archive":
        boundaries = [entry for entry in manifest if entry["source"] == "taxi_zone_boundaries"]
        if len(boundaries) != 1:
            raise ValueError("Exactly one archived boundary version is required")
        zone_evidence = boundaries[0]
        polygons = json.loads(verified_payload(cache, zone_evidence))
        for station in stations:
            checked = locate_station(station, polygons)
            if checked["zone_id"] != station["zone_id"]:
                raise ValueError("Station mapping disagrees with the saved geometry")
    records = []
    files = 0
    selected_source = "openaq_archive" if mode == "public_archive" else "openaq_hourly"
    for entry in manifest:
        if entry["source"] != selected_source:
            continue
        raw = verified_payload(cache, entry)
        station = by_id[entry["location_id"]]
        if mode == "public_archive":
            normalized = list(parse_archive(raw, station))
        else:
            body = json.loads(raw)
            normalized = [normalize_observation(row, entry["sensor_id"], entry["location_id"]) for row in body["results"]]
        if len(normalized) != entry["result_count"]:
            raise ValueError("OpenAQ file or page row count mismatch")
        files += 1
        records.extend(normalized)
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
    con.execute("CREATE OR REPLACE TABLE air_match_policy(min_hours INTEGER)")
    con.execute("INSERT INTO air_match_policy VALUES (?)", [min_hours])
    con.execute("""CREATE OR REPLACE TABLE air_hourly AS
      SELECT a.report_date, a.report_hour, a.hour_start_utc, a.location_id,
        a.pollutant_code, a.measurement_unit, avg(a.value ORDER BY a.sensor_id) AS concentration,
        count(*) AS sensor_count
      FROM silver_air_hourly a JOIN dim_date d USING(report_date)
      WHERE is_reportable
      GROUP BY a.report_date,a.report_hour,a.hour_start_utc,a.location_id,a.pollutant_code,a.measurement_unit;
      CREATE OR REPLACE TABLE fact_air_quality_daily AS
      SELECT report_date, location_id, pollutant_code, measurement_unit,
        count(*) AS observed_hour_count, sum(concentration ORDER BY hour_start_utc) AS concentration_sum,
        avg(concentration ORDER BY hour_start_utc) AS concentration_mean
      FROM air_hourly GROUP BY report_date, location_id, pollutant_code, measurement_unit;
      CREATE OR REPLACE TABLE matched_air_taxi AS
      WITH air AS (
        SELECT a.report_date,l.zone_id,a.pollutant_code,a.measurement_unit,
          avg(a.concentration_mean ORDER BY a.location_id) AS concentration, count(*) AS station_count,
          min(a.observed_hour_count) AS min_observed_hours
        FROM fact_air_quality_daily a JOIN dim_air_location l USING(location_id)
        WHERE l.zone_id IS NOT NULL AND l.zone_id <> -1
          AND a.observed_hour_count >= (SELECT min_hours FROM air_match_policy)
        GROUP BY a.report_date,l.zone_id,a.pollutant_code,a.measurement_unit
      ) SELECT t.report_date,t.pickup_zone_id,t.trip_count,a.pollutant_code,
          a.measurement_unit,a.concentration,a.station_count,a.min_observed_hours
        FROM fact_taxi_daily t JOIN air a
          ON a.report_date=t.report_date AND a.zone_id=t.pickup_zone_id;
      CREATE OR REPLACE TABLE air_taxi_correlation AS
      SELECT pickup_zone_id,pollutant_code,measurement_unit,count(*) AS matched_days,
        CASE WHEN count(*) >= 3 AND min(trip_count) < max(trip_count) AND min(concentration) < max(concentration)
             THEN corr(trip_count,concentration ORDER BY report_date) END AS pearson_r
      FROM matched_air_taxi GROUP BY pickup_zone_id,pollutant_code,measurement_unit""")
    daily_rows = con.execute("SELECT count(*) FROM fact_air_quality_daily").fetchone()[0]
    if not daily_rows:
        raise ValueError("No reportable OpenAQ observations match the reporting window")
    if con.execute("SELECT count(*) FROM fact_air_quality_daily WHERE observed_hour_count > 25").fetchone()[0]:
        raise ValueError("More observations than hours in a local calendar day")
    if con.execute("""SELECT count(*) FROM (SELECT report_date,pickup_zone_id,pollutant_code,measurement_unit
        FROM matched_air_taxi GROUP BY ALL HAVING count(*) > 1)""").fetchone()[0]:
        raise ValueError("Matched air/taxi rows do not have a unique day-zone-pollutant-unit grain")
    return {"status": "passed", "source_rows": len(records), "exact_duplicate_rows": duplicate_count,
        "silver_rows": len(clean), "non_reportable_rows": sum(not r["is_reportable"] for r in clean),
        "daily_rows": daily_rows, "run_id": info["run_id"], "source_mode": mode,
        "original_files": files, "stations": stations, "boundaries": zone_evidence,
        "archive_coverage": info.get("archive_coverage"), "min_hours_for_pair": min_hours,
        "matched_days_by_series": con.execute("SELECT sum(matched_days) FROM air_taxi_correlation").fetchone()[0] or 0,
        "series_count": con.execute("SELECT count(*) FROM air_taxi_correlation").fetchone()[0],
        "no_source_flag_count": sum(r["source_flagged"] is None for r in clean),
        "tables": ["dim_air_location", "air_hourly", "fact_air_quality_daily", "matched_air_taxi", "air_taxi_correlation"]}
