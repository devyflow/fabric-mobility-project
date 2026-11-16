"""Build importable notebooks from readable, versioned Python cell sources."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in sorted((ROOT / "notebooks/source").glob("*.py")):
    cells = []
    for block in source.read_text(encoding="utf-8").split("# CELL ")[1:]:
        kind, content = block.split("\n", 1)
        content = content.rstrip() + "\n"
        if kind == "markdown":
            content = "\n".join(line.removeprefix("# ").removeprefix("#") for line in content.splitlines()) + "\n"
            cells.append({"cell_type": "markdown", "metadata": {}, "source": content.splitlines(keepends=True)})
        elif kind == "code":
            ast.parse(content)
            cells.append({"cell_type": "code", "metadata": {}, "source": content.splitlines(keepends=True), "execution_count": None, "outputs": []})
        else:
            raise ValueError(f"Unknown cell type {kind}")
    notebook = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    for i, cell in enumerate(cells):
        cell["id"] = f"cell-{i:03d}"
    destination = ROOT / "notebooks" / (source.stem + ".ipynb")
    destination.write_text(json.dumps(notebook, indent=2) + "\n", encoding="utf-8")
    print(f"Built {destination.name}: {len(cells)} cells; Python syntax checked")
