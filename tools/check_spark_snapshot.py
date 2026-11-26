"""Run the Databricks notebook's transformations with local PySpark."""

import argparse
import json
import runpy
from pathlib import Path

from pyspark.sql import SparkSession


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="+", help="Staged month folders")
    parser.add_argument("--evidence", type=Path, required=True, help="JSON output file")
    args = parser.parse_args()
    spark = (SparkSession.builder.master("local[3]").appName("NYC mobility verification")
        .config("spark.ui.enabled", "false").config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.shuffle.partitions", "12").config("spark.driver.memory", "2g").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    notebook = runpy.run_path(str(ROOT / "databricks/nyc_mobility.py"))
    try:
        results = []
        for path in args.input:
            evidence, _, _ = notebook["build"](spark, path)
            results.append(evidence)
            print(f"Validated {evidence['month']} with Spark {spark.version}", flush=True)
    finally:
        spark.stop()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(results, default=str, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
