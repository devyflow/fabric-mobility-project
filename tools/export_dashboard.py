"""Export dashboard data from checked Databricks snapshots using the official CLI."""

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "databricks/publish_dashboard.py"
TERMINAL_STATES = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR", "BLOCKED"}


def export(cli, profile, notebook, selections, output):
    def run_cli(*args):
        result = subprocess.run(
            [cli, *map(str, args), "--profile", profile, "-o", "json"],
            capture_output=True, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout)

    request = {
        "run_name": "NYC Mobility | Publish Dashboard",
        "performance_target": "PERFORMANCE_OPTIMIZED",
        "timeout_seconds": 900,
        "tasks": [{"task_key": "publish_dashboard", "notebook_task": {
            "notebook_path": notebook, "source": "WORKSPACE",
            "base_parameters": {"snapshots": json.dumps(selections)},
        }}],
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "publish.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        run_id = run_cli("jobs", "submit", "--no-wait", "--json", f"@{path}")["run_id"]

    print(f"Started Databricks publication run {run_id}", flush=True)
    previous = None
    deadline = time.monotonic() + 960
    while time.monotonic() < deadline:
        run = run_cli("jobs", "get-run", run_id)
        status = run["state"]["life_cycle_state"]
        task = run.get("tasks", [{}])[0]
        task_status = task.get("state", {}).get("life_cycle_state")
        if (status, task_status) != previous:
            print(f"Publication is {status}, task {task_status}", flush=True)
            previous = (status, task_status)
        if status in TERMINAL_STATES:
            break
        time.sleep(12)
    else:
        raise TimeoutError(f"Databricks publication is still running: {run_id}")

    if run["state"].get("result_state") != "SUCCESS":
        error = run_cli("jobs", "get-run-output", task["run_id"]).get("error") if task.get("run_id") else None
        raise RuntimeError(error or run["state"]["state_message"])
    notebook_output = run_cli("jobs", "get-run-output", task["run_id"])["notebook_output"]
    if notebook_output.get("truncated"):
        raise ValueError("Databricks truncated the dashboard result")
    result = json.loads(notebook_output["result"])
    dashboard = result["dashboard"]
    encoded = json.dumps(dashboard, allow_nan=False, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    if result["dashboard_sha256"] != digest or dashboard["platform"] != "Databricks Delta":
        raise ValueError("Dashboard results differ from the checked Databricks publication")

    catalog, schema = result["reporting_schema"].split(".")
    tables = run_cli("tables", "list", catalog, schema, "--omit-columns", "--omit-username")
    expected = {"publication_evidence"}
    for month in dashboard["snapshots"]:
        names = ["fact_air_quality_daily", "fact_air_zone_daily", "matched_taxi_air_daily"]
        if month["epa_quality"]:
            names.append("silver_epa_no2")
        expected.update(f"{name}_{month['month'].replace('-', '_')}" for name in names)
    if {table["name"] for table in tables} != expected or any(table["data_source_format"] != "DELTA" for table in tables):
        raise ValueError("Unity Catalog does not contain the expected reporting Delta tables")

    evidence = {
        "job_result": "SUCCESS", "execution": "Databricks serverless Lakeflow Job",
        "dashboard_sha256": digest, "managed_reporting_tables_verified": len(tables),
        "notebook_sha256": hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest(),
        "months": [{
            "month": month["month"], "trips": month["total"]["trips"],
            "station_days": len(month["station_days"]), "matched_air_taxi_days": len(month["pairs"]),
            "pollutants": sorted({row["pollutant"] for row in month["station_days"]}),
            "epa": month["epa_quality"],
        } for month in dashboard["snapshots"]],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "dashboard.json").write_bytes((encoded + "\n").encode())
    (output / "dashboard_evidence.json").write_bytes((json.dumps(evidence, indent=2) + "\n").encode())
    print(f"Verified {len(tables)} managed Delta tables and exported {len(dashboard['snapshots'])} months")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", default="databricks", help="Official Databricks CLI executable")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--notebook", required=True, help="Workspace path of publish_dashboard.py")
    parser.add_argument("--snapshot", action="append", required=True, metavar="SCHEMA[=EPA_VOLUME_FOLDER]")
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    selections = []
    for selection in args.snapshot:
        schema, _, epa_folder = selection.partition("=")
        selections.append({"schema": schema, "epa_directory": epa_folder or None})
    export(args.cli, args.profile, args.notebook, selections, args.output)
