# CELL markdown
# # Inspect the taxi source
#
# Purpose: establish what arrived before changing any values.
# Run in a Fabric PySpark notebook with the project Lakehouse attached.
# Prerequisite: the taxi Copy Pipeline has landed the selected file at the path below.
# This notebook has not been executed in Fabric yet. No output is fabricated.
#
# Explain it: Bronze is the original evidence. I inspect its schema, count its rows,
# and measure unusual values before deciding what to transform.

# CELL code
sample_month = "2025-06"

# CELL code
import re

# Fabric applies pipeline overrides immediately after the parameter cell.
if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", sample_month):
    raise ValueError("Expected YYYY-MM")
source_path = f"Files/bronze/nyc_taxi/source_month={sample_month}/yellow_tripdata_{sample_month}.parquet"

# CELL markdown
# ## Read the original file
# Spark reads the Parquet schema. We do not change or delete source records.

# CELL code
from pyspark.sql import functions as F

taxi = spark.read.parquet(source_path)
required = {"tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID", "trip_distance", "fare_amount", "total_amount"}
missing = required - set(taxi.columns)
if missing:
    raise ValueError(f"Required fields missing: {sorted(missing)}")
taxi.printSchema()
display(taxi.limit(10))

# CELL markdown
# ## Measure the data
# Zero distance is a review category, not a deletion rule.
# Null fare and zero fare mean different things; count them separately.

# CELL code
profile = taxi.agg(
    F.count("*").alias("source_rows"),
    F.sum(F.when(F.col("trip_distance") == 0, 1).otherwise(0)).alias("zero_distance_rows"),
    F.sum(F.when((F.col("trip_distance") == 0) & (F.col("fare_amount") > 0), 1).otherwise(0)).alias("zero_distance_positive_fare_rows"),
    F.sum(F.when(F.col("fare_amount").isNull(), 1).otherwise(0)).alias("null_fare_rows"),
    F.sum(F.when(F.col("fare_amount") < 0, 1).otherwise(0)).alias("negative_fare_rows"),
    F.min("tpep_pickup_datetime").alias("first_pickup"),
    F.max("tpep_pickup_datetime").alias("last_pickup"),
)
display(profile)

# CELL markdown
# ## Explain the result
# Record the actual row count and anomaly counts in the project evidence.
# A source file labelled June can contain dates outside June. Preserve these records;
# source_month identifies the delivery batch, while pickup_date identifies the trip date.
# Do not claim a record is invalid solely because it falls outside the filename month.
