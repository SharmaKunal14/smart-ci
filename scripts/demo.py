"""Offline fixture demo; no test execution or model calls."""

import json
from pathlib import Path

from smartci.contracts import Inventory
from smartci.reports import atomic_write, markdown
from smartci.selection import Changes, Graph, SelectionPolicy, select

root = Path("fixtures/selection")
out = Path("demo-output")
out.mkdir(exist_ok=True)
inv = Inventory.model_validate_json((root / "inventory.json").read_bytes())
base = Graph.model_validate_json((root / "base-graph.json").read_bytes())
head = Graph.model_validate_json((root / "head-graph.json").read_bytes())
policy = SelectionPolicy.model_validate_json((root / "policy.json").read_bytes())
for name in ("narrow", "broad"):
    changes = Changes.model_validate_json((root / f"{name}.json").read_bytes())
    report = select(changes, inv, base, head, policy)
    atomic_write(
        out / f"{name}.selection.json", json.dumps(report.model_dump(), indent=2) + "\n"
    )
    atomic_write(out / f"{name}.audit.md", markdown(report))
    print(name, report.mode, report.selected, report.fallback)
