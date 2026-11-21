"""Check that report assets, notebook cells and pipeline dependencies are usable."""
import ast
import base64
import json
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

pipeline = json.loads((ROOT / "pipelines/master.spec.json").read_text(encoding="utf-8"))
activities = {row["name"]: row for row in pipeline["activities"]}
assert len(activities) == len(pipeline["activities"])
done, remaining = set(), set(activities)
while remaining:
    ready = {name for name in remaining if set(activities[name]["depends_on"]) <= done}
    assert ready, "Pipeline has a cycle or missing dependency"
    done.update(ready)
    remaining -= ready
evidence = json.loads((ROOT / "reports/local_build.json").read_text(encoding="utf-8"))
assert all(check["passed"] for check in evidence["validation"]["checks"])
assert evidence["validation"]["source_rows"] == evidence["validation"]["silver_rows"]
print(f"Verified {len(parser.local_links)} report links, {parser.images} embedded charts, six parameterized notebooks, an acyclic pipeline specification, and passing reconciliation evidence")
