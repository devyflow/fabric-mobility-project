# CELL markdown
# # Build daily taxi measures and calendar exchange rates
# This notebook rebuilds a small reporting window from Silver. Set the same
# window in all reporting items. Load Silver FX far enough back to cover the
# seven-day rate policy, including the week before the first reporting day.

# CELL code
start_date = "2025-06-01"
end_date = "2025-06-30"    # Inclusive, development sample
max_fx_age_days = 7

# CELL code
from datetime import date, timedelta
from pyspark.sql import functions as F
from pyspark.sql.window import Window

start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
if end < start or (end - start).days > 3660 or not 0 <= max_fx_age_days <= 30:
    raise ValueError("Invalid reporting window or FX freshness limit")
days = [(start + timedelta(days=n),) for n in range((end - start).days + 1)]
dates = (spark.createDataFrame(days, "report_date date")
    .withColumn("year", F.year("report_date"))
    .withColumn("month", F.month("report_date"))
    .withColumn("day_of_week", F.dayofweek("report_date")))

# CELL markdown
# ## One eligible FX row per reporting date
# Choose the latest valid published rate on or before the date. An unmatched
# day remains in the calendar with a null rate. This prevents missing weekends
# from dropping taxi records or several currency rows from inflating revenue.

# CELL code
fx = spark.table("silver_fx").where(F.col("is_valid_rate"))
if fx.groupBy("source_rate_date").count().where("count > 1").limit(1).count():
    raise ValueError("Duplicate Silver FX dates")
effective_fx = (dates.select("report_date")
    .join(fx, (F.col("source_rate_date") <= F.col("report_date")) &
          (F.datediff("report_date", "source_rate_date") <= max_fx_age_days), "left")
    .withColumn("rank", F.row_number().over(Window.partitionBy("report_date").orderBy(F.col("source_rate_date").desc_nulls_last())))
    .where("rank = 1").drop("rank")
    .withColumn("currency_pair", F.lit("USD/EUR"))
    .withColumn("rate_age_days", F.datediff("report_date", "source_rate_date"))
    .select("report_date", "currency_pair", "source_rate_date", "usd_per_eur", "rate_age_days"))
assert effective_fx.count() == len(days)

# CELL markdown
# ## Aggregate one row per pickup date and zone
# Measures are totals and denominators, so report averages are weighted by trip
# counts. USD and EUR averages use a matched FX cohort when comparing currencies.
# The original values and quality flags remain in Silver. Null dates are excluded
# from this reporting window and counted explicitly below.

# CELL code
zones_raw = (spark.read.option("header", True)
    .csv("Files/bronze/taxi_zones/taxi_zone_lookup.csv"))
zones = zones_raw.select(F.expr("try_cast(LocationID as int)").alias("zone_id"),
    F.col("Borough").alias("borough"), F.col("Zone").alias("zone_name"), "service_zone")
if zones.where("zone_id IS NULL OR zone_id = -1").limit(1).count() or zones.groupBy("zone_id").count().where("count > 1").limit(1).count():
    raise ValueError("Taxi zone lookup contains invalid or duplicate keys")
zones = zones.unionByName(spark.createDataFrame([(-1, "Unknown", "Unknown", None)],
    "zone_id int, borough string, zone_name string, service_zone string"))
trips = spark.table("silver_taxi_trips")
quality_counts = (trips.agg(
    F.count("*").alias("silver_rows"),
    F.count(F.when(F.col("pickup_date").isNull(), 1)).alias("missing_pickup_date"),
    F.count(F.when(F.col("pickup_date").between(start, end), 1)).alias("in_reporting_window"),
    F.count(F.when(F.col("pickup_date").isNotNull() & ~F.col("pickup_date").between(start, end), 1)).alias("outside_reporting_window")
).first())
assert quality_counts.silver_rows == quality_counts.missing_pickup_date + quality_counts.in_reporting_window + quality_counts.outside_reporting_window
base = (trips.where(F.col("pickup_date").between(start, end))
        .withColumnRenamed("pickup_date", "report_date")
        .join(F.broadcast(zones.select("zone_id")), F.expr("try_cast(PULocationID as int) = zone_id"), "left")
        .withColumn("pickup_zone_id", F.coalesce(F.col("zone_id"), F.lit(-1))))
daily = (base.groupBy("report_date", "pickup_zone_id").agg(
    F.count("*").alias("trip_count"),
    F.count("fare_usd").alias("known_base_fare_count"),
    F.count("total_charged_usd").alias("known_charge_count"),
    F.count(F.when(F.array_contains("quality_flags", "zero_distance"), 1)).alias("zero_distance_trip_count"),
    F.sum("fare_usd").alias("base_fare_usd"),
    F.sum("total_charged_usd").alias("total_charged_usd")
).join(effective_fx, "report_date", "left")
    .withColumn("base_fare_eur", (F.col("base_fare_usd") / F.col("usd_per_eur")).cast("decimal(28,4)"))
    .withColumn("total_charged_eur", (F.col("total_charged_usd") / F.col("usd_per_eur")).cast("decimal(28,4)"))
    .withColumn("fx_covered_charge_count", F.when(F.col("usd_per_eur").isNotNull(), F.col("known_charge_count")).otherwise(F.lit(0)))
    .withColumn("fx_covered_charge_usd", F.when(F.col("usd_per_eur").isNotNull(), F.col("total_charged_usd")))
    .drop("source_rate_date", "usd_per_eur", "rate_age_days", "currency_pair"))
assert (daily.agg(F.sum("trip_count")).first()[0] or 0) == quality_counts.in_reporting_window
hourly = base.groupBy("report_date", "pickup_hour", "pickup_zone_id").agg(F.count("*").alias("trip_count"))
assert (hourly.agg(F.sum("trip_count")).first()[0] or 0) == quality_counts.in_reporting_window
print(quality_counts.asDict())

# CELL markdown
# ## Save the reporting window
# These are full rebuilds of the configured analysis window. The Silver detail
# is retained. Pipeline deployment must serialize these rebuilds and publish only
# after joint taxi and air-quality checks pass.

# CELL code
for name, frame in (("gold_dim_date", dates), ("gold_dim_fx", effective_fx), ("gold_dim_zone", zones),
                    ("gold_fact_taxi_daily", daily), ("gold_taxi_hourly", hourly)):
    frame.write.format("delta").mode("overwrite").saveAsTable(name)
display(daily.orderBy(F.col("trip_count").desc()).limit(10))
