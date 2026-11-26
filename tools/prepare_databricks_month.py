"""Capture, check, and optionally upload a source month for the Databricks job."""

import argparse
import json
import os
import re
import subprocess
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def prepare(args):
    start = date.fromisoformat(f"{args.month}-01")
    end = start.replace(day=monthrange(start.year, start.month)[1])
    work = args.work_dir.resolve()
    cache = (args.reuse_captures or (work / "bronze")).resolve()
    if work.exists():
        raise ValueError("Use a new work directory for each refresh")
    work.mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT / "src"), env.get("PYTHONPATH"))))

    def run_python(*parts):
        subprocess.run([sys.executable, *map(str, parts)], cwd=ROOT, env=env, check=True)

    if not args.reuse_captures:
        # Include the reporting year even when collecting a month outside the demo.
        config = json.loads((ROOT / "config/project.json").read_bytes())
        config.update(gdp_start_year=start.year - 1, gdp_end_year=start.year)
        config_path = work / "project.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        run_python("-m", "fabric_project.preflight", "--config", config_path, "--month", args.month,
                   "--cache", cache, "--report-dir", work / "preflight", "--download-taxi", "--skip-openaq-api")
        boundaries = ["--boundaries-file", args.boundaries_file.resolve()] if args.boundaries_file else []
        run_python("-m", "fabric_project.openaq_archive", "--cache", cache, "--start", start, "--end", end, *boundaries)

    build = work / "builds"
    folder = work / "staged"
    run_python("-m", "fabric_project.local_build", "--cache", cache, "--workspace", build, "--start", start,
               "--end", end, "--require-air", "--report", work / "evidence.json")
    run_python("tools/stage_databricks.py", "--cache", cache, "--build", build, "--output", folder)
    if args.volume_root:
        manifest = json.loads((folder / "manifest.json").read_bytes())
        destination = f"{args.volume_root.rstrip('/')}/{args.month}-{manifest['local_reference_run'][:12]}"

        def run_cli(*parts):
            subprocess.run([args.cli, *map(str, parts), "--profile", args.profile], check=True)

        run_cli("fs", "mkdir", f"dbfs:{destination}")
        for name in sorted(manifest["files"]):
            run_cli("fs", "cp", folder / name, f"dbfs:{destination}/{name}")
        run_cli("fs", "cp", folder / "manifest.json", f"dbfs:{destination}/manifest.json")
        print(f"Set the Lakeflow job input_directory to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="Published TLC month formatted as YYYY-MM")
    parser.add_argument("--work-dir", required=True, type=Path, help="New scratch directory")
    parser.add_argument("--reuse-captures", type=Path, help="Read a previously verified Bronze cache")
    parser.add_argument("--boundaries-file", type=Path, help="Use a saved official NYC Taxi Zones GeoJSON")
    parser.add_argument("--volume-root", help="Existing /Volumes/catalog/schema/volume folder")
    parser.add_argument("--profile", help="Databricks CLI profile for upload")
    parser.add_argument("--cli", default="databricks")
    args = parser.parse_args()
    if args.volume_root and (not args.profile or not re.fullmatch(r"/Volumes/[^/]+/[^/]+/[^/]+(?:/.*)?", args.volume_root)):
        parser.error("--volume-root requires a Unity Catalog volume path and --profile")
    prepare(args)
