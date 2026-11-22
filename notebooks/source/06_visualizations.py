# CELL markdown
# # Explore mobility, air quality and economics
# Run after Gold reconciliation and Warehouse publication. These notebook charts
# satisfy the visualization requirement once real source data and execution are
# verified. Use a single pollutant/unit and measured station geography for the
# environmental comparison. This file contains no precomputed findings.

# CELL code
pollutant_code = "pm25"
measurement_unit = "µg/m³"  # Use the exact unit spelling returned by the Dataflow.
minimum_observed_hours = 18
minimum_matched_days = 3

# CELL code
from pyspark.sql import functions as F
import matplotlib.pyplot as plt

def small_frame(frame, maximum_rows=10000):
    if frame.limit(maximum_rows+1).count() > maximum_rows:
        raise ValueError("Aggregate or filter the report before collecting it")
    return frame.toPandas()

taxi = spark.table("gold_fact_taxi_daily")
zones = spark.table("gold_dim_zone")
daily = taxi.groupBy("report_date").agg(
    F.sum("trip_count").alias("trips"), F.sum("base_fare_usd").alias("fare_usd"),
    F.sum("known_base_fare_count").alias("known_fares"),
    F.sum("fx_covered_charge_usd").alias("matched_usd"),
    F.sum("total_charged_eur").alias("matched_eur"),
    F.sum("fx_covered_charge_count").alias("matched_charge_count"))
mobility = small_frame(daily.orderBy("report_date"))
top_zones = small_frame(taxi.join(zones, taxi.pickup_zone_id == zones.zone_id)
    .groupBy("zone_name").agg(F.sum("trip_count").alias("trips"))
    .orderBy(F.desc("trips")).limit(10))
fig, axes = plt.subplots(1,2,figsize=(14,4),layout="constrained")
axes[0].plot(mobility.report_date, mobility.trips)
axes[0].set(title="Taxi trips by reporting day",ylabel="Recorded trips")
axes[1].barh(top_zones.zone_name.iloc[::-1], top_zones.trips.iloc[::-1])
axes[1].set(title="Busiest pickup zones",xlabel="Recorded trips")
display(fig)
plt.close(fig)

# CELL markdown
# ## USD and EUR on the same cohort
# The denominator is the count of charge-bearing records with a usable FX rate.
# GDP is shown separately at country/year grain. Never sum annual GDP after
# expanding it across daily taxi observations.

# CELL code
mobility["avg_charge_usd"] = mobility.matched_usd.astype(float) / mobility.matched_charge_count.replace(0, float("nan"))
mobility["avg_charge_eur"] = mobility.matched_eur.astype(float) / mobility.matched_charge_count.replace(0, float("nan"))
gdp = small_frame(spark.table("silver_gdp").where("country_code='USA'").orderBy("year"))
fig, axes = plt.subplots(1,2,figsize=(13,4),layout="constrained")
axes[0].plot(mobility.report_date,mobility.avg_charge_usd,label="USD")
axes[0].plot(mobility.report_date,mobility.avg_charge_eur,label="EUR")
axes[0].set(title="Average recorded charge per eligible trip",ylabel="Currency units")
axes[0].legend()
axes[1].bar(gdp.year.astype(str),gdp.gdp_current_usd.astype(float)/1e12)
axes[1].set(title="US annual nominal GDP",ylabel="Trillion current USD")
display(fig)
plt.close(fig)

# CELL markdown
# ## Pollutant trends and coverage
# Each line is a measured station, not a claim about unmonitored taxi zones.
# Observed-hour counts are shown alongside means so a partial day is visible.

# CELL code
air = spark.table("gold_fact_air_quality_daily").where(
    (F.col("pollutant_code") == pollutant_code) & (F.col("measurement_unit") == measurement_unit))
if not air.limit(1).count():
    raise ValueError("No actual observations for this pollutant/unit. Inspect available units; do not generate a placeholder chart")
air_frame = small_frame(air.orderBy("report_date", "location_id"))
fig, axes = plt.subplots(1,2,figsize=(13,4),layout="constrained")
for station, rows in air_frame.groupby("location_id"):
    axes[0].plot(rows.report_date,rows.concentration_mean,label=f"Station {station}")
    axes[1].plot(rows.report_date,rows.observed_hour_count,label=f"Station {station}")
axes[0].set(title=f"Daily {pollutant_code} concentration",ylabel=measurement_unit)
axes[1].set(title="Station coverage",ylabel="Observed hours")
axes[0].legend(); axes[1].legend()
display(fig)
plt.close(fig)

# CELL markdown
# ## Match date and measured geography before correlation
# Average stations equally within a mapped zone/day. Join this aggregate to one
# taxi fact row per zone/day, avoiding sensor-level multiplication of trips.
# Retain low-coverage dates in the chart above and omit them from pairs.
# Report sample count. A correlation is an association and cannot prove causation.
# One month cannot establish seasonality or a long-term economic relationship.

# CELL code
locations = spark.table("gold_dim_air_location")
if locations.groupBy("location_id").count().where("count > 1").limit(1).count():
    raise ValueError("Location mapping is not unique")
zone_air = (air.join(locations, "location_id")
    .where(F.col("zone_id").isNotNull() & (F.col("zone_id") != -1)
           & (F.col("observed_hour_count") >= minimum_observed_hours))
    .groupBy("report_date", "zone_id")
    .agg(F.avg("concentration_mean").alias("concentration"), F.count("*").alias("station_count")))
pairs = taxi.join(zone_air,(taxi.report_date == zone_air.report_date) & (taxi.pickup_zone_id == zone_air.zone_id))
summary = pairs.groupBy("pickup_zone_id").agg(
    F.count("*").alias("matched_days"),
    F.min("trip_count").alias("min_trips"), F.max("trip_count").alias("max_trips"),
    F.min("concentration").alias("min_air"), F.max("concentration").alias("max_air"),
    F.corr("trip_count", "concentration").alias("r")
).select("pickup_zone_id", "matched_days",
    F.when((F.col("matched_days") >= minimum_matched_days) & (F.col("min_trips") < F.col("max_trips"))
           & (F.col("min_air") < F.col("max_air")), F.col("r")).alias("pearson_r"))
display(summary.orderBy(F.desc("matched_days")))
eligible = summary.where(F.col("matched_days") >= minimum_matched_days).select("pickup_zone_id")
points = small_frame(pairs.join(eligible, "pickup_zone_id").select("pickup_zone_id","trip_count","concentration"))
if points.empty:
    print("No zone has sufficient paired days for the configured demonstration threshold; inspect geography and coverage")
else:
    fig, axis = plt.subplots(figsize=(8,5),layout="constrained")
    for zone, rows in points.groupby("pickup_zone_id"):
        axis.scatter(rows.trip_count,rows.concentration,alpha=.65,label=f"Zone {zone}")
    axis.set(title=f"Paired daily trips and {pollutant_code}",xlabel="Recorded taxi trips",ylabel=measurement_unit)
    axis.legend()
    display(fig)
    plt.close(fig)
