# Databricks notebook source
# MAGIC %md
# MAGIC # Publish the mobility dashboard
# MAGIC Read checked Delta snapshots. Export small aggregates with no workspace credentials or trip-level records.

# COMMAND ----------

import csv
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql.window import Window


TIME_ZONE = "America/New_York"
AIR_KEYS = ["pollutant", "unit", "source"]
EPA_SCHEMA = (
    "station_id STRING, monitor INT, hour_start_utc TIMESTAMP, concentration DOUBLE, "
    "qualifier STRING, quality_flag STRING"
)


def checked_snapshot(spark, name):
    if not re.fullmatch(r"[a-z][a-z0-9_]*\.mobility_\d{4}_\d{2}_[0-9a-f]{12}", name):
        raise ValueError("Select the catalog and schema of a completed mobility snapshot")
    entries = spark.table(f"{name}.run_evidence").take(2)
    if len(entries) != 1:
        raise ValueError("There must be exactly one validation record")
    evidence = json.loads(entries[0].evidence_json)
    if (evidence["status"] != "passed" or evidence["execution"] != "databricks_delta"
            or evidence["schema"].replace("`", "") != name):
        raise ValueError("Only validated Databricks Delta snapshots can be published")
    return evidence


def epa_air(spark, directory, month):
    directory = Path(directory)
    if not re.fullmatch(r"/Volumes/[^/]+/[^/]+/[^/]+/.+", str(directory)):
        raise ValueError("Select a staged EPA AQS folder in a Unity Catalog volume")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if manifest["month"] != month or set(manifest["files"]) != {"hourly.csv", "stations.json"}:
        raise ValueError("EPA manifest does not describe this month")
    for name, expected in manifest["files"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"EPA source checksum differs: {name}")

    rows = []
    with (directory / "hourly.csv").open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            station = f"aqs:{row['State Code']}-{row['County Code']}-{row['Site Num']}"
            utc = datetime.fromisoformat(f"{row['Date GMT']}T{row['Time GMT']}").replace(tzinfo=timezone.utc)
            value = float(row["Sample Measurement"]) if row["Sample Measurement"] else None
            flag = "missing_or_nonfinite" if value is None or not math.isfinite(value) else None
            if flag:
                value = None
            elif value < 0:
                flag = "negative_concentration"
            if utc.minute or utc.second or row["Parameter Code"] != "42602" or row["Units of Measure"] != "Parts per billion":
                raise ValueError("EPA input is outside the hourly NO2/ppb contract")
            rows.append((station, int(row["POC"]), utc, value, row["Qualifier"] or None, flag))

    locations = spark.createDataFrame(json.loads((directory / "stations.json").read_bytes()))
    if len(rows) != manifest["nyc_slice_rows"] or locations.count() != manifest["nyc_site_count"]:
        raise ValueError("EPA row or station count differs from the capture")
    silver = (spark.createDataFrame(rows, EPA_SCHEMA)
        .withColumn("report_date", F.to_date(F.from_utc_timestamp("hour_start_utc", TIME_ZONE))))
    if silver.join(locations, "station_id", "left_anti").take(1):
        raise ValueError("EPA monitor is missing its reviewed taxi-zone assignment")

    # Keep all source rows in Silver. Select the best-covered instrument per site to avoid
    # double-counting parallel monitors. Break equal coverage by smaller EPA occurrence code.
    in_month = silver.where(F.date_format("report_date", "yyyy-MM") == month)
    valid = in_month.where("quality_flag IS NULL")
    rank = Window.partitionBy("station_id").orderBy(F.desc("hours"), "monitor")
    monitors = (valid.groupBy("station_id", "monitor").agg(F.countDistinct("hour_start_utc").alias("hours"))
        .withColumn("rank", F.row_number().over(rank)).where("rank = 1").select("station_id", "monitor"))
    selected = (valid.join(monitors, ["station_id", "monitor"])
        .select("report_date", "hour_start_utc", "station_id", "concentration").distinct())
    if selected.groupBy("station_id", "hour_start_utc").count().where("count > 1").take(1):
        raise ValueError("A selected EPA instrument has conflicting hourly values")
    hourly = (selected.withColumn("pollutant", F.lit("no2")).withColumn("unit", F.lit("ppb"))
        .withColumn("source", F.lit("EPA AQS")))
    quality = {
        "source": manifest["source"], "annual_archive_sha256": manifest["annual_archive_sha256"],
        "slice_rows": len(rows), "sites": manifest["nyc_site_count"], "in_month_rows": in_month.count(),
        "excluded_quality_rows": in_month.where("quality_flag IS NOT NULL").count(),
        "qualified_in_month_rows": in_month.where("qualifier IS NOT NULL").count(),
        "published_hourly_rows": hourly.count(),
    }
    if quality["published_hourly_rows"] == 0:
        raise ValueError("The EPA file contains no eligible in-month readings")
    return hourly, locations.select("station_id", "station_name", "zone_id"), silver, quality


def json_rows(frame, *order):
    return [row.asDict() for row in frame.orderBy(*order).collect()]


def air_reports(spark, namespace, taxi, minimum_hours, month, epa_directory, save):
    locations = spark.table(f"{namespace}.dim_air_location").select(
        F.concat(F.lit("openaq:"), F.col("location_id")).alias("station_id"), "station_name", "zone_id")
    hourly = spark.table(f"{namespace}.air_hourly").select(
        "report_date", "hour_start_utc", F.concat(F.lit("openaq:"), F.col("location_id")).alias("station_id"),
        F.col("pollutant_code").alias("pollutant"), F.col("measurement_unit").alias("unit"),
        F.lit("OpenAQ").alias("source"), "concentration")
    epa_quality = None
    if epa_directory:
        epa_hours, epa_locations, epa_silver, epa_quality = epa_air(spark, epa_directory, month)
        save("silver_epa_no2", epa_silver)
        hourly = hourly.unionByName(epa_hours)
        locations = locations.unionByName(epa_locations)
    if locations.groupBy("station_id").count().where("count <> 1").take(1):
        raise ValueError("Station IDs must be unique before the air-to-zone join")

    zones = spark.table(f"{namespace}.dim_zone").select("zone_id", "zone_name")
    locations = locations.join(zones, "zone_id")
    daily = save("fact_air_quality_daily", hourly.groupBy("report_date", "station_id", *AIR_KEYS)
        .agg(F.count("*").alias("observed_hours"), F.avg("concentration").alias("concentration")))
    zone_daily = save("fact_air_zone_daily", daily.where(F.col("observed_hours") >= minimum_hours)
        .join(locations, "station_id").groupBy("report_date", "zone_id", *AIR_KEYS).agg(
            F.avg("concentration").alias("concentration"), F.count("*").alias("station_count"),
            F.min("observed_hours").alias("min_observed_hours")))
    pairs = save("matched_taxi_air_daily", zone_daily.join(
        taxi.select("report_date", "zone_id", "trip_count"), ["report_date", "zone_id"]))
    correlations = (pairs.groupBy("zone_id", *AIR_KEYS).agg(
        F.count("*").alias("matched_days"), F.corr("trip_count", "concentration").alias("r"),
        F.stddev_pop("trip_count").alias("trip_sigma"), F.stddev_pop("concentration").alias("air_sigma"))
        .select("zone_id", *AIR_KEYS, "matched_days",
                F.when(F.expr("matched_days >= 3 AND trip_sigma > 0 AND air_sigma > 0"), F.col("r")).alias("r")))

    station_hours = (hourly.withColumn("pickup_hour", F.hour(F.from_utc_timestamp("hour_start_utc", TIME_ZONE)))
        .groupBy("report_date", "pickup_hour", "station_id", *AIR_KEYS)
        .agg(F.avg("concentration").alias("concentration")))
    zone_hours = (station_hours.join(locations, "station_id").groupBy("report_date", "pickup_hour", "zone_id", *AIR_KEYS)
        .agg(F.avg("concentration").alias("concentration")))
    taxi_hours = spark.table(f"{namespace}.taxi_hourly").withColumnRenamed("pickup_zone_id", "zone_id")
    paired_hours = zone_hours.join(taxi_hours, ["report_date", "pickup_hour", "zone_id"])
    profiles = (paired_hours.groupBy("pickup_hour", "zone_id", *AIR_KEYS).agg(
        F.count("*").alias("matched_days"), F.avg("trip_count").alias("average_trips"),
        F.avg("concentration").alias("concentration")))
    return {
        "station_days": json_rows(daily.join(locations, "station_id"), "station_id", *AIR_KEYS, "report_date"),
        "pairs": json_rows(pairs.join(zones, "zone_id"), "zone_id", *AIR_KEYS, "report_date"),
        "correlations": json_rows(correlations.join(zones, "zone_id"), "zone_id", *AIR_KEYS),
        "paired_hour_profile": json_rows(profiles, "zone_id", *AIR_KEYS, "pickup_hour"),
        "epa_quality": epa_quality,
    }


def snapshot(spark, namespace, reporting, epa_directory=None):
    evidence = checked_snapshot(spark, namespace)
    month = evidence["month"]
    suffix = month.replace("-", "_")

    def save(name, frame):
        target = f"{reporting}.{name}_{suffix}"
        frame.write.format("delta").saveAsTable(target)
        return spark.table(target)

    taxi = spark.table(f"{namespace}.fact_taxi_daily").withColumnRenamed("pickup_zone_id", "zone_id")
    zones = spark.table(f"{namespace}.dim_zone").select("zone_id", "borough", "zone_name")
    fx = spark.table(f"{namespace}.dim_fx").select("report_date", "usd_per_eur", "source_rate_date", "rate_age_days")
    sums = (
        F.sum("trip_count").alias("trips"), F.sum("zero_distance_trip_count").alias("zero_distance_trips"),
        F.sum("known_base_fare_count").alias("fare_count"), F.sum("base_fare_usd").alias("base_fare_usd"),
        F.sum("total_charged_usd").alias("charged_usd"),
        F.sum("fx_covered_charge_count").alias("fx_trip_count"),
        F.sum("fx_covered_charge_usd").alias("matched_usd"), F.sum("total_charged_eur").alias("matched_eur"),
    )
    total = taxi.agg(*sums).first().asDict()
    check = evidence["checks"]
    if total["trips"] != check["reporting_rows"] or str(total["charged_usd"]) != check["total_charged_usd"]:
        raise ValueError("Exported totals differ from validated taxi totals")
    daily = taxi.groupBy("report_date").agg(*sums).join(fx, "report_date")
    zone_rank = (taxi.groupBy("zone_id").agg(F.sum("trip_count").alias("trips")).join(zones, "zone_id")
        .orderBy(F.desc("trips"), "zone_id").limit(12))
    hourly = spark.table(f"{namespace}.taxi_hourly").groupBy("pickup_hour").agg(F.sum("trip_count").alias("trips"))
    if hourly.agg(F.sum("trips")).first()[0] != total["trips"]:
        raise ValueError("Hourly export does not reconcile to the same trip count")
    year = int(month[:4])
    gdp = spark.table(f"{namespace}.dim_gdp").where(F.col("year") == year).select("year", "gdp_current_usd")
    return {
        "month": month, "spark_version": evidence["spark_version"],
        "quality": {key: check[key] for key in (
            "source_rows", "silver_rows", "outside_reporting_window_rows", "missing_pickup_date_rows",
            "uncovered_fx_dates", "air_silver_rows", "rejected_air_rows")},
        "min_air_hours": evidence["min_air_hours"], "total": total, "days": json_rows(daily, "report_date"),
        "zones": [row.asDict() for row in zone_rank.collect()], "hourly": json_rows(hourly, "pickup_hour"),
        "gdp": json_rows(gdp, "year"),
        **air_reports(spark, namespace, taxi, evidence["min_air_hours"], month, epa_directory, save),
    }


if "dbutils" in globals():
    dbutils.widgets.text("snapshots", "[]")
    selections = json.loads(dbutils.widgets.get("snapshots"))
    if not selections:
        raise ValueError("Provide a list of successful snapshot schemas and their optional EPA folders")
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    catalog = selections[0]["schema"].split(".")[0]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", catalog):
        raise ValueError("Invalid Unity Catalog name")
    reporting = f"{catalog}.mobility_reporting_{uuid.uuid4().hex[:12]}"
    spark.sql(f"CREATE SCHEMA {reporting}")
    snapshots = [snapshot(spark, item["schema"], reporting, item.get("epa_directory")) for item in selections]
    if len({item["month"] for item in snapshots}) != len(snapshots):
        raise ValueError("Publish each source month once")
    result = {"version": 1, "platform": "Databricks Delta", "snapshots": snapshots}
    encoded = json.dumps(result, default=str, allow_nan=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    spark.createDataFrame([(datetime.now(timezone.utc), len(snapshots), digest)],
        "published_at_utc TIMESTAMP, snapshot_count INT, dashboard_sha256 STRING"
    ).write.format("delta").saveAsTable(f"{reporting}.publication_evidence")
    dbutils.notebook.exit(json.dumps(
        {"reporting_schema": reporting, "dashboard_sha256": digest, "dashboard": result}, default=str, allow_nan=False))
