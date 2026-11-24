"""Check that report assets, notebook cells and pipeline dependencies are usable."""
import ast
import base64
import csv
import hashlib
import json
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.local_links = []
        self.images = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            target = attributes.get("href", "")
            if target and not target.startswith(("https://", "http://", "#")):
                self.local_links.append(target)
        if tag == "img":
            payload = attributes["src"].removeprefix("data:image/png;base64,")
            if not attributes.get("alt") or base64.b64decode(payload)[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Missing alt text or invalid embedded PNG")
            self.images += 1


parser = ReportParser()
parser.feed((ROOT / "reports/project_report.html").read_text(encoding="utf-8"))
assert parser.images >= 2
for target in parser.local_links:
    path = (ROOT / "reports" / unquote(target)).resolve()
    assert path.is_relative_to(ROOT.resolve()) and path.is_file(), f"Broken report link: {target}"

notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
assert len(notebooks) == 6
for file in notebooks:
    notebook = json.loads(file.read_text(encoding="utf-8"))
    code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    assert code and code[0]["metadata"].get("tags") == ["parameters"]
    for cell in code:
        ast.parse("".join(cell["source"]))
        assert cell["outputs"] == [], "Do not package invented execution output"
    if file.stem in ("01_inspect_taxi_bronze", "02_taxi_silver"):
        # Run the pure Python setup in the same order as a notebook parameter override.
        values = {}
        exec("".join(code[0]["source"]), values)
        values["sample_month"] = "2024-06"
        exec("".join(code[1]["source"]), values)
        expected_path = "Files/bronze/nyc_taxi/source_month=2024-06/yellow_tripdata_2024-06.parquet"
        assert values["source_path"] == expected_path, f"Month override ignored in {file.name}"

pipeline = json.loads((ROOT / "pipelines/master.spec.json").read_text(encoding="utf-8"))
activities = {row["name"]: row for row in pipeline["activities"]}
assert len(activities) == len(pipeline["activities"])
done, remaining = set(), set(activities)
while remaining:
    ready = {name for name in remaining if set(activities[name]["depends_on"]) <= done}
    assert ready, "Pipeline has a cycle or missing dependency"
    done.update(ready)
    remaining -= ready
evidence_names = ["local_build.json"]
if "comparison_build.json" in parser.local_links:
    evidence_names.append("comparison_build.json")
for name in evidence_names:
    evidence = json.loads((ROOT / "reports" / name).read_text(encoding="utf-8"))
    validation = evidence["validation"]
    assert all(check["passed"] for check in validation["checks"])
    assert validation["source_rows"] == validation["silver_rows"]
    assert validation["silver_rows"] == sum(validation[key] for key in (
        "reporting_rows", "missing_pickup_date_rows", "outside_reporting_window_rows"))
    if len(evidence_names) == 2:
        assert evidence["openaq"]["status"] == "passed"
        assert evidence["same_input_rerun"].startswith("passed")
    for file, expected in evidence["transformation_source_sha256"].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == expected, f"Build source has changed: {file}"

if "tables/matched_air_taxi.csv" in parser.local_links:
    series_columns = ("pickup_zone_id", "pollutant_code", "measurement_unit")
    with (ROOT / "reports/tables/matched_air_taxi.csv").open(encoding="utf-8", newline="") as stream:
        pairs = list(csv.DictReader(stream))
    with (ROOT / "reports/tables/air_taxi_correlation.csv").open(encoding="utf-8", newline="") as stream:
        summaries = list(csv.DictReader(stream))
    series_counts = Counter(tuple(row[key] for key in series_columns) for row in pairs)
    assert len(pairs) == len({tuple(row[key] for key in ("report_date", *series_columns)) for row in pairs})
    assert series_counts == {tuple(row[key] for key in series_columns): int(row["matched_days"]) for row in summaries}
    assert parser.images >= 4

print(f"Verified {len(parser.local_links)} report links, {parser.images} charts, six notebooks, taxi month overrides, "
      f"pipeline dependencies, and reconciled evidence for {len(evidence_names)} run(s)")
