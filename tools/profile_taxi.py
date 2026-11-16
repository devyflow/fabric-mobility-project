"""Profile a downloaded Parquet file locally (requires PyArrow)."""
import argparse
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("parquet", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
dataset = pq.ParquetFile(args.parquet)
fields = ["trip_distance", "fare_amount", "tpep_pickup_datetime"]
counts = dict(source_rows=0, zero_distance_rows=0, zero_distance_positive_fare_rows=0,
              missing_fare_rows=0, negative_fare_rows=0)
first_pickup, last_pickup, example = None, None, None
for batch in dataset.iter_batches(columns=fields):
    distance, fare, pickup = (batch.column(batch.schema.get_field_index(name)) for name in fields)
    zero = pc.equal(distance, 0)
    positive_fare = pc.and_kleene(zero, pc.greater(fare, 0))
    counts["source_rows"] += batch.num_rows
    counts["zero_distance_rows"] += pc.sum(zero).as_py() or 0
    counts["zero_distance_positive_fare_rows"] += pc.sum(positive_fare).as_py() or 0
    counts["missing_fare_rows"] += fare.null_count
    counts["negative_fare_rows"] += pc.sum(pc.less(fare, 0)).as_py() or 0
    bounds = pc.min_max(pickup).as_py()
    if bounds["min"] is not None:
        first_pickup = min(first_pickup or bounds["min"], bounds["min"])
        last_pickup = max(last_pickup or bounds["max"], bounds["max"])
    if example is None:
        examples = pc.filter(fare, positive_fare)
        if len(examples):
            example = {"distance_miles": 0, "base_fare_usd": examples[0].as_py()}
if counts["source_rows"] != dataset.metadata.num_rows:
    raise RuntimeError("Profile row count differs from Parquet metadata")
result = {
    "scope": "Local profile of actual source Parquet, not a Fabric run",
    "file": args.parquet.name,
    **counts,
    "first_recorded_pickup": str(first_pickup),
    "last_recorded_pickup": str(last_pickup),
    "example_zero_distance_positive_fare": example,
}
formatted = json.dumps(result, indent=2) + "\n"
print(formatted, end="")
if args.output:
    args.output.write_text(formatted, encoding="utf-8")
