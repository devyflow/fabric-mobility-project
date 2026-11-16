# CELL markdown
# # Normalize hourly air quality and build daily station measures
# Run only after authentic OpenAQ results are staged. Use a verified sensor-to-
# station mapping, including a nullable zone ID. This step deliberately does
# not assign unmeasured zones a concentration.

# CELL code
run_id = "set-a-successful-openaq-run-id"
start_date = "2025-06-01"
end_date = "2025-06-07"

# CELL code
from pyspark.sql import functions as F
from pyspark.sql.window import Window

# Time fields coming from OpenAQ are UTC with offsets. Derive New York dates
# and hours from the actual interval start; an ending midnight belongs to the
# previous hour. Retain the UTC interval to disambiguate repeated DST hours.
spark.conf.set("spark.sql.session.timeZone", "UTC")
mapping = spark.table("ref_air_sensor").select("sensor_id", "location_id", "station_name", "latitude", "longitude", "zone_id")
if mapping.where("sensor_id IS NULL OR location_id IS NULL").limit(1).count() or mapping.groupBy("sensor_id").count().where("count > 1").limit(1).count():
    raise ValueError("Sensor reference must have one known location per sensor")
pages = (spark.table("bronze_openaq_hourly_pages").where(F.col("run_id") == run_id)
         .select("sensor_id", "page", "result_count", "payload_json").distinct())
if not pages.limit(1).count():
    raise ValueError("No pages for the requested OpenAQ run")
if pages.groupBy("sensor_id", "page").count().where("count > 1").limit(1).count():
    raise ValueError("Conflicting repeats in selected API batch")
coverage = pages.groupBy("sensor_id").agg(
    F.min("page").alias("first_page"), F.max("page").alias("last_page"),
    F.count("*").alias("page_count"))
if coverage.where("first_page <> 1 OR last_page <> page_count").limit(1).count():
    raise ValueError("API pages are missing")

# CELL markdown
# ## Expand the original response and reconcile counts
# Retain original values and create flags for rows that cannot contribute to an
# average. Conflicting duplicate hours fail visibly; exact duplicates remain
# traceable in Bronze and are counted separately.

# CELL code
result_schema = ("struct<results:array<struct<value:double,"
    "parameter:struct<name:string,units:string>,flagInfo:struct<hasFlags:boolean>,"
    "period:struct<datetimeFrom:struct<utc:string>,datetimeTo:struct<utc:string>>>>>")
parsed = pages.withColumn("results", F.from_json("payload_json", result_schema)["results"])
if parsed.where(F.col("results").isNull() | (F.size("results") != F.col("result_count"))).limit(1).count():
    raise ValueError("OpenAQ result counts do not match the saved API pages")
rows = (parsed.select("sensor_id", "page", F.explode("results").alias("row"))
    .select("sensor_id", "page", F.col("row.value").alias("value"),
        F.lower(F.trim(F.col("row.parameter.name"))).alias("pollutant_code"),
        F.trim(F.col("row.parameter.units")).alias("measurement_unit"),
        F.col("row.flagInfo.hasFlags").alias("source_flagged"),
        F.col("row.period.datetimeFrom.utc").alias("source_from_utc"),
        F.col("row.period.datetimeTo.utc").alias("source_to_utc")))
expected_rows = pages.agg(F.sum("result_count")).first()[0]
if not expected_rows:
    raise ValueError("The OpenAQ batch contains no measurements; check sensor coverage")
assert rows.count() == expected_rows
dedup_columns = [c for c in rows.columns if c != "page"]
dedup = rows.select(*dedup_columns).distinct()
clean = (dedup.join(mapping, "sensor_id", "left")
    .withColumn("hour_start_utc", F.expr("try_cast(source_from_utc as timestamp)"))
    .withColumn("hour_end_utc", F.expr("try_cast(source_to_utc as timestamp)"))
    .withColumn("hour_start_nyc", F.from_utc_timestamp("hour_start_utc", "America/New_York"))
    .withColumn("report_date", F.to_date("hour_start_nyc"))
    .withColumn("report_hour", F.hour("hour_start_nyc"))
    .withColumn("is_reportable", F.coalesce(
         F.col("location_id").isNotNull() & F.col("hour_start_utc").isNotNull()
         & (F.col("hour_end_utc") > F.col("hour_start_utc"))
         & (F.length("pollutant_code") > 0) & (F.length("measurement_unit") > 0)
         & F.col("value").isNotNull() & ~F.isnan("value")
         & (F.abs(F.col("value")) != float("inf")) & (F.col("value") >= 0)
         & (F.col("source_flagged") == F.lit(False)), F.lit(False)))
    .withColumn("source_run_id", F.lit(run_id)))
if clean.where("hour_start_utc IS NOT NULL").groupBy("sensor_id", "hour_start_utc").count().where("count > 1").limit(1).count():
    raise ValueError("Conflicting measurements for the same sensor and hour")
silver_count = clean.count()
print({"source_rows": expected_rows, "silver_rows": silver_count,
       "exact_duplicate_rows": expected_rows - silver_count,
       "not_reportable_rows": clean.where("NOT is_reportable").count()})

# CELL markdown
# ## Average comparable station hours
# Equal-weight sensors observing the same pollutant in the same unit and hour.
# Then equal-weight available hours for that station/day. Keeping unit in the
# grain prevents an average that mixes ppb and mass concentration. The count
# records coverage; missing hours never become zero.

# CELL code
eligible = clean.where(F.col("is_reportable") & F.col("report_date").between(start_date, end_date))
hourly = eligible.groupBy("report_date", "report_hour", "hour_start_utc", "location_id", "pollutant_code", "measurement_unit").agg(
    F.avg("value").alias("concentration"), F.count("*").alias("sensor_count"))
daily = hourly.groupBy("report_date", "location_id", "pollutant_code", "measurement_unit").agg(
    F.count("*").cast("int").alias("observed_hour_count"),
    F.sum("concentration").alias("concentration_sum"),
    F.avg("concentration").alias("concentration_mean"))
if not daily.limit(1).count():
    raise ValueError("No reportable observations in the selected window")
locations = mapping.drop("sensor_id").distinct()
if locations.groupBy("location_id").count().where("count > 1").limit(1).count():
    raise ValueError("Conflicting station metadata in reference")
for name, frame in (("silver_air_hourly", clean), ("gold_air_hourly", hourly),
                    ("gold_fact_air_quality_daily", daily), ("gold_dim_air_location", locations)):
    frame.write.format("delta").mode("overwrite").saveAsTable(name)
display(daily.orderBy("report_date", "location_id").limit(20))
