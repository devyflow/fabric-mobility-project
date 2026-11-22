"""Download, verify, and report on the two course demonstration months."""
import argparse
import os
import subprocess
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERIODS = ("2025-06", "2024-06")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data" / "demo")
    parser.add_argument("--primary-cache", type=Path, help="Existing or new Bronze directory for June 2025")
    parser.add_argument("--comparison-cache", type=Path, help="Existing or new Bronze directory for June 2024")
    parser.add_argument("--reuse-captures", action="store_true", help="Rebuild from previously downloaded files")
    args = parser.parse_args()
    work = args.work_dir.resolve()
    caches = [
        (path or work / month / "bronze").resolve()
        for path, month in zip((args.primary_cache, args.comparison_cache), PERIODS)
    ]
    if caches[0] == caches[1]:
        parser.error("Use one Bronze directory per source month")
    sys.path.insert(0, str(ROOT / "src"))
    from fabric_project.local_build import find_inputs

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT / "src"), env.get("PYTHONPATH"))))

    def run(*command):
        subprocess.run([sys.executable, *(str(part) for part in command)], cwd=ROOT, env=env, check=True)

    workspaces = []
    for month, cache in zip(PERIODS, caches):
        period = work / month
        first = date.fromisoformat(f"{month}-01")
        last = first.replace(day=monthrange(first.year, first.month)[1])
        print(f"Processing {month}", flush=True)
        if not args.reuse_captures:
            run("-m", "fabric_project.preflight", "--month", month, "--cache", cache, "--report-dir",
                period / "preflight", "--download-taxi", "--skip-openaq-api")
            run("-m", "fabric_project.openaq_archive", "--cache", cache, "--start", first, "--end", last)
        # Confirm the two supplied caches really belong to the two reporting months.
        source = find_inputs(cache)["nyc_taxi"]
        if not source["source_url"].endswith(f"/yellow_tripdata_{month}.parquet"):
            raise ValueError(f"Cached taxi source does not match {month}")
        workspace = period / "builds"
        run("-m", "fabric_project.local_build", "--cache", cache, "--workspace", workspace,
            "--start", first, "--end", last, "--require-air", "--prove-rerun", "--report", period / "evidence.json")
        workspaces.append(workspace)
    run("tools/render_local_report.py", "--workspace", workspaces[0], "--comparison-workspace", workspaces[1])
    run("tools/verify_artifacts.py")


if __name__ == "__main__":
    main()
