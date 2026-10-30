"""Source-derived check for 2026 standard-estimate maintenance section 4-2-1."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity

spec_path = next(f for f in (ROOT / "data/drafts/specs").rglob("4-2-1.json")
                 if json.loads(f.read_text(encoding="utf-8"))["draft"]["quantity_model"]["name"] == "formula"
                 and "base_labor" in [field["name"] for field in
                                      json.loads(f.read_text(encoding="utf-8"))["draft"]["inputs"]])
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
work_type = next(field["allowed_values"] for field in spec["inputs"]
                 if field["name"] == "work_type")

# PDF p. 924, table 4-2-1: the listed six installation items use 40% for
# removal and 140% for relocation. With a source installation amount of 100,
# these independently yield 40 and 140 person-days.
for operation, expected in zip(work_type, (40, 140)):
    result = formula_quantity(spec, {"work_type": operation, "base_labor": 100})
    assert result["status"] == "computed", result
    line = result["unit_lines"][0]
    assert line["exact"] == str(expected) and line["unit"] == "인", line
    assert line["citations"] and "40%" in line["citations"][0]["quote"]
    assert "140%" in line["citations"][0]["quote"]

print("4-2-1 source-rate checks passed: removal and relocation coefficients, units, and source citation")
