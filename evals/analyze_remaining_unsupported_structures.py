"""Compactly group current calculator skips by declared source-table shape; does not run estimates."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
packages = {}
for path in (ROOT / "data/drafts/specs").rglob("*.json"):
    package = json.loads(path.read_text(encoding="utf-8"))
    packages[package["draft"]["id"]] = package
numeric = re.compile(r"^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:\s*%|\s*)\s*$")
rows = []
for skip in INDEX["skipped"]:
    if skip.get("stage") != "calculator_selection":
        continue
    package = packages[skip["id"]]
    draft = package["draft"]
    tables = draft.get("tables", [])
    values = [cell for table in tables for row in table.get("values", {}).values()
              for cell in row.values()]
    units = sorted({str(table.get("unit")) for table in tables if table.get("unit")})
    numeric_cells = sum(bool(numeric.fullmatch(str(value))) for value in values)
    rows.append({"id": skip["id"], "calc_type": package.get("calc_type"),
                 "title": draft.get("title"), "table_count": len(tables),
                 "populated_tables": sum(bool(table.get("values")) for table in tables),
                 "value_cell_count": len(values), "numeric_cell_count": numeric_cells,
                 "unit_signatures": units, "input_units": sorted({str(x.get("unit")) for x in draft.get("inputs", []) if x.get("unit")}),
                 "input_count": len(draft.get("inputs", [])), "not_calculable_reason": package.get("calc_type_reason", ""),
                 "steps": draft.get("quantity_model", {}).get("steps", [])[:2]})

group_counts = Counter((row["calc_type"], "empty-table" if not row["populated_tables"] else
                        "no-numeric-cells" if not row["numeric_cell_count"] else
                        "numeric-table", "multi-unit" if len(row["unit_signatures"]) > 1 else
                        "single-or-unspecified-unit") for row in rows)
candidates = sorted((row for row in rows if row["calc_type"] == "not_calculable"
                     and 1 <= row["numeric_cell_count"] <= 80 and row["input_count"] <= 10),
                    key=lambda row: (-row["numeric_cell_count"], row["table_count"], row["id"]))
report = {"method": "saved index and spec-structure scan only; no source/rule verification",
          "current_calculator_skips": len(rows),
          "structure_groups": [{"calc_type": key[0], "table_shape": key[1], "unit_shape": key[2], "count": count}
                               for key, count in sorted(group_counts.items())],
          "candidate_count": len(candidates), "top_candidates": candidates[:45]}
out = ROOT / "evals/runtime_validation/unsupported-candidate-structure-scan-2026-10-19.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"method": report["method"], "current_calculator_skips": len(rows),
                  "structure_groups": report["structure_groups"],
                  "candidate_count": len(candidates),
                  "top_candidates": [{k: c[k] for k in ("id", "numeric_cell_count", "input_count", "unit_signatures")}
                                     for c in candidates[:15]]}, ensure_ascii=False, indent=2))
