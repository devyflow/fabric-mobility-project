# Databricks notebook source
# MAGIC %md
# MAGIC # NYC mobility on Databricks
# MAGIC Upload the files prepared by `tools/stage_databricks.py` to a Unity Catalog volume.
# MAGIC This notebook builds a new Delta snapshot and checks it against the verified local run.

# COMMAND ----------

import hashlib
import json
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql.window import Window


if "dbutils" in globals():
    dbutils.widgets.text("input_directory", "")
    dbutils.widgets.text("catalog", "workspace")


def spark_path(path):
    return str(path) if path.as_posix().startswith("/Volumes/") else path.as_uri()


def load_manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    start, end = (date.fromisoformat(manifest[key]) for key in ("start_date", "end_date"))
    if end < start or end.strftime("%Y-%m") != start.strftime("%Y-%m") or start.strftime("%Y-%m") != manifest["month"]:
        raise ValueError("The Bronze manifest must describe one source month")
    expected_files = {
        "yellow_taxi.parquet", "taxi_zones.csv", "ecb_fx.csv", "world_bank_gdp.json",
        "air_hourly.jsonl", "air_locations.jsonl", "openaq_originals.zip",
    }
    if set(manifest["files"]) != expected_files or not 1 <= manifest["min_air_hours"] <= 25:
        raise ValueError("Incomplete or invalid Bronze manifest")
    for filename, expected in manifest["files"].items():
        digest = hashlib.sha256()
        with (directory / filename).open("rb") as payload:
            for block in iter(lambda: payload.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"File checksum mismatch: {filename}")
    return manifest, start, end


def require_unique(frame, keys):
    if frame.groupBy(*keys).count().where("count > 1").take(1):
        raise ValueError(f"Repeated key in {keys}")


# COMMAND ----------
# MAGIC %md
# MAGIC ## Reference tables
# MAGIC The date table includes weekends. Each day gets the most recent valid ECB rate up to
# MAGIC seven days old. GDP stays annual.

# COMMAND ----------


def reference_tables(spark, directory, start, end):
    days = (spark.range((end - start).days + 1)
        .select(F.date_add(F.lit(start), F.col("id").cast("int")).alias("report_date"))
        .withColumn("year", F.year("report_date"))
        .withColumn("month", F.month("report_date"))
        .withColumn("day_of_week", F.dayofweek("report_date")))

    raw_zones = spark.read.option("header", True).csv(spark_path(directory / "taxi_zones.csv"))
    zones = raw_zones.select(F.expr("try_cast(LocationID AS INT)").alias("zone_id"),
        F.col("Borough").alias("borough"), F.col("Zone").alias("zone_name"), "service_zone")
    require_unique(zones, ("zone_id",))
    if zones.where("zone_id IS NULL OR zone_id = -1").take(1):
        raise ValueError("Invalid zone key")
    zones = zones.unionByName(spark.sql("SELECT -1 AS zone_id, 'Unknown' AS borough, 'Unknown' AS zone_name, cast(NULL as STRING) AS service_zone"))

    fx_raw = spark.read.option("header", True).csv(spark_path(directory / "ecb_fx.csv"))
    if fx_raw.where("NOT (CURRENCY <=> 'USD' AND CURRENCY_DENOM <=> 'EUR')").take(1):
        raise ValueError("ECB quote must be USD per EUR")
    fx = fx_raw.select(F.to_date("TIME_PERIOD").alias("source_rate_date"),
        F.expr("try_cast(OBS_VALUE AS DECIMAL(18,8))").alias("usd_per_eur"),
        F.col("OBS_STATUS").alias("observation_status"))
    require_unique(fx, ("source_rate_date",))
    age = F.datediff("report_date", "source_rate_date")
    ranking = Window.partitionBy("report_date").orderBy(F.desc_nulls_last("source_rate_date"))
    effective_fx = (days.select("report_date")
        .join(F.broadcast(fx.where("usd_per_eur > 0")), age.between(0, 7), "left")
        .withColumn("rank", F.row_number().over(ranking)).where("rank = 1")
        .select("report_date", F.lit("USD/EUR").alias("currency_pair"),
            "source_rate_date", "usd_per_eur", age.alias("rate_age_days")))

    metadata, records = json.loads((directory / "world_bank_gdp.json").read_text(encoding="utf-8"))
    if int(metadata["pages"]) != 1 or int(metadata["total"]) != len(records) or not records:
        raise ValueError("The GDP response must contain the complete annual selection")
    gdp = spark.createDataFrame([
        (row["countryiso3code"], int(row["date"]), row["indicator"]["id"],
         Decimal(str(row["value"])) if row["value"] is not None else None)
        for row in records
    ], "country_code STRING, year INT, indicator_code STRING, gdp_current_usd DECIMAL(28,2)")
    require_unique(gdp, ("country_code", "year", "indicator_code"))
    return {"dim_date": days, "dim_zone": zones, "dim_fx": effective_fx, "dim_gdp": gdp}, fx


# COMMAND ----------
# MAGIC %md
# MAGIC ## Taxi Silver and Gold
# MAGIC Preserve every source record. A zero-mile trip still contributes to counts and money.
# MAGIC Gold groups by NYC pickup date and zone before attaching the exchange rate.

# COMMAND ----------


def taxi_silver(raw, filename):
    typed = raw.select("*",
        F.expr("try_cast(tpep_pickup_datetime AS TIMESTAMP_NTZ)").alias("pickup_ts"),
        F.expr("try_cast(tpep_dropoff_datetime AS TIMESTAMP_NTZ)").alias("dropoff_ts"),
        F.expr("try_cast(PULocationID AS INT)").alias("original_zone_id"),
        F.expr("try_cast(trip_distance AS DOUBLE)").alias("distance_miles"),
        F.expr("try_cast(fare_amount AS DECIMAL(18,4))").alias("fare_usd"),
        F.expr("try_cast(total_amount AS DECIMAL(18,4))").alias("total_charged_usd"),
        F.lit(filename).alias("source_file"))
    typed = (typed.withColumn("pickup_date", F.to_date("pickup_ts"))
        .withColumn("pickup_hour", F.hour("pickup_ts"))
        .withColumn("duration_seconds", F.expr("timestampdiff(SECOND, pickup_ts, dropoff_ts)")))
    flags = {
        "missing_distance": "distance_miles IS NULL",
        "nonfinite_distance": "isnan(distance_miles) OR abs(distance_miles) = double('Infinity')",
        "zero_distance": "distance_miles = 0",
        "negative_distance": "distance_miles < 0",
        "missing_fare": "fare_usd IS NULL",
        "negative_fare_review": "fare_usd < 0",
        "missing_duration": "duration_seconds IS NULL",
        "negative_duration": "duration_seconds < 0",
        "fare_parse_error": "fare_amount IS NOT NULL AND fare_usd IS NULL",
        "total_parse_error": "total_amount IS NOT NULL AND total_charged_usd IS NULL",
        "distance_parse_error": "trip_distance IS NOT NULL AND distance_miles IS NULL",
        "pickup_parse_error": "tpep_pickup_datetime IS NOT NULL AND pickup_ts IS NULL",
        "dropoff_parse_error": "tpep_dropoff_datetime IS NOT NULL AND dropoff_ts IS NULL",
    }
    observed = F.array(*[F.when(F.expr(condition), F.lit(label)) for label, condition in flags.items()])
    return typed.withColumn("quality_flags", F.filter(observed, lambda item: item.isNotNull()))


def aggregate_taxi(silver, dimensions, start, end):
    in_window = silver.where(F.col("pickup_date").between(start, end)).withColumnRenamed("pickup_date", "report_date")
    zones = dimensions["dim_zone"].select("zone_id")
    trips = (in_window.join(F.broadcast(zones), in_window.original_zone_id == zones.zone_id, "left")
        .withColumn("pickup_zone_id", F.coalesce(F.col("zone_id"), F.lit(-1))))
    counts = (trips.groupBy("report_date", "pickup_zone_id").agg(
        F.count("*").alias("trip_count"),
        F.count("fare_usd").alias("known_base_fare_count"),
        F.count("total_charged_usd").alias("known_charge_count"),
        F.count_if(F.col("distance_miles") == 0).alias("zero_distance_trip_count"),
        F.sum("fare_usd").alias("base_fare_usd"),
        F.sum("total_charged_usd").alias("total_charged_usd")))
    daily = (counts.join(dimensions["dim_fx"].select("report_date", "usd_per_eur"), "report_date", "left")
        .withColumn("base_fare_eur", (F.col("base_fare_usd") / F.col("usd_per_eur")).cast("decimal(28,4)"))
        .withColumn("total_charged_eur", (F.col("total_charged_usd") / F.col("usd_per_eur")).cast("decimal(28,4)"))
        .withColumn("fx_covered_charge_count", F.when(F.col("usd_per_eur").isNotNull(), F.col("known_charge_count")).otherwise(0))
        .withColumn("fx_covered_charge_usd", F.when(F.col("usd_per_eur").isNotNull(), F.col("total_charged_usd")))
        .drop("usd_per_eur"))
    hourly = (trips.groupBy("report_date", "pickup_hour", "pickup_zone_id")
        .agg(F.count("*").alias("trip_count")))
    return daily, hourly


# COMMAND ----------
# MAGIC %md
# MAGIC ## Air quality and matched days
# MAGIC The prepared OpenAQ rows include the interval, station mapping, and flags from the
# MAGIC local capture. Spark averages eligible hours and joins daily totals by date and zone.

# COMMAND ----------


def air_tables(spark, directory, taxi_daily, start, end, minimum_hours):
    locations = spark.read.schema("location_id INT, station_name STRING, latitude DOUBLE, longitude DOUBLE, zone_id INT").json(
        spark_path(directory / "air_locations.jsonl"))
    require_unique(locations, ("location_id",))
    source = spark.read.schema(
        "sensor_id INT, location_id INT, hour_start_epoch LONG, hour_end_epoch LONG, "
        "pollutant_code STRING, measurement_unit STRING, value DOUBLE, quality_flags ARRAY<STRING>, "
        "is_reportable BOOLEAN, source_flagged BOOLEAN"
    ).option("mode", "FAILFAST").json(spark_path(directory / "air_hourly.jsonl"))
    silver = source.withColumn("hour_start_utc", F.timestamp_seconds("hour_start_epoch"))
    silver = silver.withColumn("report_date", F.to_date(F.from_utc_timestamp("hour_start_utc", "America/New_York")))
    if silver.join(locations, "location_id", "left_anti").take(1):
        raise ValueError("A sensor reading has no reviewed station")
    eligible = silver.where(F.col("is_reportable") & F.col("report_date").between(start, end))
    series = ["pollutant_code", "measurement_unit"]
    hourly = (eligible.groupBy("report_date", "hour_start_utc", "location_id", *series)
        .agg(F.avg("value").alias("concentration"), F.count("*").alias("sensor_count")))
    daily = (hourly.groupBy("report_date", "location_id", *series)
        .agg(F.count("*").alias("observed_hour_count"), F.sum("concentration").alias("concentration_sum"),
            F.avg("concentration").alias("concentration_mean")))
    by_zone = (daily.where(F.col("observed_hour_count") >= minimum_hours)
        .join(locations, "location_id").where("zone_id >= 0")
        .withColumnRenamed("zone_id", "pickup_zone_id").groupBy("report_date", "pickup_zone_id", *series)
        .agg(F.avg("concentration_mean").alias("concentration"),
            F.count("*").alias("station_count"), F.min("observed_hour_count").alias("min_observed_hours")))
    pairs = taxi_daily.select("report_date", "pickup_zone_id", "trip_count").join(
        by_zone, ["report_date", "pickup_zone_id"], "inner")
    correlations = (pairs.groupBy("pickup_zone_id", *series)
        .agg(F.count("*").alias("matched_days"), F.stddev_pop("trip_count").alias("trip_sigma"),
            F.stddev_pop("concentration").alias("pollution_sigma"), F.corr("trip_count", "concentration").alias("r"))
        .select("pickup_zone_id", *series, "matched_days",
            F.when(F.expr("matched_days >= 3 AND trip_sigma > 0 AND pollution_sigma > 0"), F.col("r")).alias("pearson_r")))
    return {"dim_air_location": locations, "silver_air_hourly": silver, "air_hourly": hourly,
        "fact_air_quality_daily": daily, "matched_air_taxi": pairs, "air_taxi_correlation": correlations}


# COMMAND ----------
# MAGIC %md
# MAGIC ## Check the snapshot and record what ran
# MAGIC A new run gets its own schema. The `run_evidence` table is written after the checks.

# COMMAND ----------


def validate(raw_count, silver, daily, hourly, dimensions, air, manifest, start, end):
    counts = silver.agg(
        F.count("*").alias("silver_rows"),
        F.count_if(F.col("pickup_date").isNull()).alias("missing_pickup_date_rows"),
        F.count_if(~F.col("pickup_date").between(start, end)).alias("outside_reporting_window_rows"),
    ).first().asDict()
    totals = daily.agg(F.sum("trip_count"), F.sum("zero_distance_trip_count"), F.sum("base_fare_usd"),
        F.sum("total_charged_usd"), F.sum(F.when(F.col("pickup_zone_id") == -1, F.col("trip_count")).otherwise(0))).first()
    coverage = air["silver_air_hourly"].agg(F.count("*"), F.count_if(~F.col("is_reportable"))).first()
    observed = {
        "source_rows": raw_count, **counts, "reporting_rows": totals[0],
        "zero_distance_trips_in_window": totals[1], "base_fare_usd": f"{totals[2]:.4f}",
        "total_charged_usd": f"{totals[3]:.4f}", "unknown_zone_trips": totals[4],
        "uncovered_fx_dates": dimensions["dim_fx"].where("usd_per_eur IS NULL").count(),
        "air_silver_rows": coverage[0], "rejected_air_rows": coverage[1],
        "matched_days_by_series": air["matched_air_taxi"].count(),
    }
    if set(manifest["expected"]) != set(observed):
        raise ValueError("The manifest lacks the complete set of reference checks")
    mismatches = {key: (expected, observed[key]) for key, expected in manifest["expected"].items() if observed[key] != expected}
    if mismatches:
        raise AssertionError(f"Reference comparison failed (expected, observed): {mismatches}")
    if hourly.agg(F.sum("trip_count")).first()[0] != observed["reporting_rows"]:
        raise AssertionError("Hourly taxi totals differ from daily totals")
    require_unique(daily, ("report_date", "pickup_zone_id"))
    require_unique(air["fact_air_quality_daily"], ("report_date", "location_id", "pollutant_code", "measurement_unit"))
    require_unique(air["matched_air_taxi"], ("report_date", "pickup_zone_id", "pollutant_code", "measurement_unit"))
    return observed


def table_digest(frame, keys):
    # Compare the published rows in a fixed order. Normalize harmless floating-point reduction noise.
    rows = []
    for row in frame.orderBy(*keys).collect():
        rows.append([round(value, 9) if isinstance(value, float) else value for value in row])
    encoded = json.dumps(rows, default=str, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build(spark, directory, *, catalog=None):
    directory = Path(directory).resolve()
    manifest, start, end = load_manifest(directory)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    run_id = uuid.uuid4().hex[:12]
    namespace = None
    if catalog:
        # Identifier comes from a widget. Quote it for SQL and for saveAsTable.
        quoted_catalog = "`" + catalog.replace("`", "``") + "`"
        namespace = f"{quoted_catalog}.mobility_{start:%Y_%m}_{run_id}"
        spark.sql(f"CREATE SCHEMA {namespace}")
    def save(name, frame):
        if namespace:
            target = f"{namespace}.{name}"
            frame.write.format("delta").saveAsTable(target)
            return spark.table(target)
        return frame

    raw = spark.read.parquet(spark_path(directory / "yellow_taxi.parquet"))
    source_rows = raw.count()
    silver = save("silver_taxi", taxi_silver(raw, "yellow_taxi.parquet"))
    print(f"Bronze verified: {manifest['month']}, {source_rows:,} taxi rows", flush=True)
    dimensions, fx = reference_tables(spark, directory, start, end)
    save("silver_fx", fx)
    dimensions = {name: save(name, frame) for name, frame in dimensions.items()}
    daily, hourly = aggregate_taxi(silver, dimensions, start, end)
    daily = save("fact_taxi_daily", daily)
    hourly = save("taxi_hourly", hourly)
    print("Taxi reporting tables built", flush=True)
    air = air_tables(spark, directory, daily, start, end, manifest["min_air_hours"])
    air = {name: save(name, frame) for name, frame in air.items()}
    counts = validate(source_rows, silver, daily, hourly, dimensions, air, manifest, start, end)

    mobility = (daily.groupBy("report_date")
        .agg(F.sum("trip_count").alias("trip_count"), F.sum("total_charged_usd").alias("total_charged_usd"),
            F.sum("fx_covered_charge_usd").alias("matched_charge_usd"), F.sum("total_charged_eur").alias("matched_charge_eur"),
            F.sum("base_fare_usd").alias("base_fare_usd"), F.sum("known_base_fare_count").alias("known_base_fare_count"))
        .withColumn("avg_base_fare_usd", F.try_divide("base_fare_usd", "known_base_fare_count")))
    mobility = save("mobility_daily", mobility)
    trace = (daily.where(F.col("report_date") == F.lit(start)).where("pickup_zone_id = 209")
        .select("report_date", "pickup_zone_id", "trip_count", "zero_distance_trip_count", "total_charged_usd", "total_charged_eur")
        .take(1))
    result = {
        "status": "passed", "month": manifest["month"], "run_id": run_id, "spark_version": spark.version,
        "execution": "databricks_delta" if namespace else "local_spark_queries",
        "schema": namespace, "local_reference_run": manifest["local_reference_run"],
        "openaq_capture_run": manifest["openaq_capture_run"], "input_sha256": manifest["files"],
        "min_air_hours": manifest["min_air_hours"], "checks": counts, "seaport_first_day": trace[0].asDict() if trace else None,
        "reporting_table_sha256": {
            "fact_taxi_daily": table_digest(daily, ("report_date", "pickup_zone_id")),
            "fact_air_quality_daily": table_digest(air["fact_air_quality_daily"],
                ("report_date", "location_id", "pollutant_code", "measurement_unit")),
            "matched_air_taxi": table_digest(air["matched_air_taxi"],
                ("report_date", "pickup_zone_id", "pollutant_code", "measurement_unit")),
        },
    }
    encoded = json.dumps(result, default=str, sort_keys=True)
    if namespace:
        save("run_evidence", spark.range(1).select(F.lit(encoded).alias("evidence_json")))
    return result, mobility, air["air_taxi_correlation"]


# COMMAND ----------

if "dbutils" in globals():
    input_directory = dbutils.widgets.get("input_directory")
    if not re.fullmatch(r"/Volumes/[^/]+/[^/]+/[^/]+/.+", input_directory):
        raise ValueError("Set input_directory to the volume folder containing manifest.json")
    catalog = dbutils.widgets.get("catalog").strip()
    if not catalog:
        raise ValueError("Set catalog to a Unity Catalog where you can create schemas")
    evidence, mobility, correlation = build(spark, input_directory, catalog=catalog)
    print(json.dumps(evidence, indent=2, default=str))
    display(mobility.orderBy("report_date"))
    display(correlation.orderBy("pickup_zone_id", "pollutant_code"))
    dbutils.notebook.exit(json.dumps(evidence, default=str))
