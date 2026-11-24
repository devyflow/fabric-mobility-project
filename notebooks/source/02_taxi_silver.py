# CELL markdown
# # Prepare taxi data in Silver
#
# Purpose: keep every original row and add standardized fields and explicit quality flags.
# Prerequisite: run notebook 01 against the same source file.
# The final write replaces only this source-month partition, so reruns do not append
# another copy of the month. Run one writer per source-month; pipeline concurrency
# controls will be configured during Fabric deployment.
#
# Status: authored for Fabric; not yet executed there.

# CELL code
sample_month = "2025-06"
silver_table = "silver_taxi_trips"

# CELL code
import re

# Fabric applies pipeline overrides immediately after the parameter cell.
if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", sample_month):
    raise ValueError("Expected YYYY-MM")
source_path = f"Files/bronze/nyc_taxi/source_month={sample_month}/yellow_tripdata_{sample_month}.parquet"

# CELL markdown
# ## Read and validate the contract
# Fail visibly when a required column disappears. Do not replace missing columns
# with invented values. Unknown additional columns remain in the output.

# CELL code
from pyspark.sql import functions as F
from pyspark.sql.window import Window

spark.conf.set("spark.sql.session.timeZone", "America/New_York")
raw = spark.read.parquet(source_path)
required = {"tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID", "trip_distance", "fare_amount", "total_amount"}
if required - set(raw.columns):
    raise ValueError(f"Missing required columns: {sorted(required - set(raw.columns))}")

# CELL markdown
# ## Add standardized columns without erasing source values
# Decimal monetary columns avoid binary floating-point rounding in reporting.
# Failed conversions become null in the new column and receive a parse-error flag;
# the original field remains available. Duration is provisional elapsed time using
# the declared New York convention. Source timestamps without offsets are ambiguous
# around daylight-saving transitions; retain them and disclose that limitation.

# CELL code
silver = (raw
    .withColumn("pickup_ts", F.expr("try_cast(tpep_pickup_datetime as timestamp)"))
    .withColumn("dropoff_ts", F.expr("try_cast(tpep_dropoff_datetime as timestamp)"))
    .withColumn("fare_usd", F.expr("try_cast(fare_amount as decimal(18,4))"))
    .withColumn("total_charged_usd", F.expr("try_cast(total_amount as decimal(18,4))"))
    .withColumn("distance_miles", F.expr("try_cast(trip_distance as double)"))
    .withColumn("pickup_date", F.to_date("pickup_ts"))
    .withColumn("pickup_hour", F.hour("pickup_ts"))
    .withColumn("duration_seconds", F.col("dropoff_ts").cast("long") - F.col("pickup_ts").cast("long"))
    .withColumn("source_month", F.lit(sample_month))
    .withColumn("source_file", F.lit(source_path))
    .withColumn("processed_at_utc", F.current_timestamp())
)

# CELL markdown
# ## Record quality observations
# Keep unusual rows. A flag is evidence for investigation, not permission to delete.
# An identical-row hash identifies candidates for duplicate review. It is not a
# globally unique trip ID, and matching rows are not automatically removed.

# CELL code
checks = [
    (F.col("distance_miles").isNull(), "missing_distance"),
    (F.isnan("distance_miles"), "nonfinite_distance"),
    (F.abs(F.col("distance_miles")) == float("inf"), "nonfinite_distance"),
    (F.col("distance_miles") == 0, "zero_distance"),
    (F.col("distance_miles") < 0, "negative_distance"),
    (F.col("fare_usd").isNull(), "missing_fare"),
    (F.col("fare_usd") < 0, "negative_fare_review"),
    (F.col("duration_seconds").isNull(), "missing_duration"),
    (F.col("duration_seconds") < 0, "negative_duration"),
    (F.col("fare_amount").isNotNull() & F.col("fare_usd").isNull(), "fare_parse_error"),
    (F.col("total_amount").isNotNull() & F.col("total_charged_usd").isNull(), "total_parse_error"),
    (F.col("trip_distance").isNotNull() & F.col("distance_miles").isNull(), "distance_parse_error"),
    (F.col("tpep_pickup_datetime").isNotNull() & F.col("pickup_ts").isNull(), "pickup_parse_error"),
    (F.col("tpep_dropoff_datetime").isNotNull() & F.col("dropoff_ts").isNull(), "dropoff_parse_error"),
]
silver = silver.withColumn("quality_flags", F.array_distinct(F.filter(F.array(*[F.when(condition, F.lit(label)) for condition, label in checks]), lambda value: value.isNotNull())))
silver = silver.withColumn("source_row_hash", F.sha2(F.to_json(F.struct(*[F.col(c) for c in sorted(raw.columns)]), {"ignoreNullFields": "false"}), 256))
silver = silver.withColumn("identical_row_count_in_file", F.count("*").over(Window.partitionBy("source_row_hash")))

# CELL markdown
# ## Reconcile before writing
# For this transformation, retained rows must equal source rows. We do not drop
# records. Business deduplication remains a documented review task; ingestion
# deduplication is achieved by replacing the specific source-month partition.

# CELL code
source_count = raw.count()
silver_count = silver.count()
assert silver_count == source_count, "Unexpected row loss or multiplication"
display(silver.select("pickup_date", "fare_usd", "distance_miles", "quality_flags").limit(20))

# CELL markdown
# ## Save the selected partition as Delta
# replaceWhere protects the other loaded months. The notebook must not use a
# whole-table overwrite for a single month. Schema drift that prevents writing
# is an explicit failure requiring review rather than an automatic schema change.

# CELL code
(silver.write.format("delta")
    .mode("overwrite")
    .option("replaceWhere", f"source_month = '{sample_month}'")
    .partitionBy("source_month")
    .saveAsTable(silver_table))
written_count = spark.table(silver_table).where(F.col("source_month") == sample_month).count()
assert written_count == source_count, "Written partition failed reconciliation"
print({"source_rows": source_count, "silver_rows": written_count, "source_month": sample_month})

# CELL markdown
# ## Breakdown session explanation
# I preserved the source fields, added typed reporting fields, and recorded quality
# flags. I checked row counts before and after writing. Rerunning the same month
# replaces its partition instead of appending duplicate trips. I have not claimed
# that identical-looking source rows must be duplicate journeys.
