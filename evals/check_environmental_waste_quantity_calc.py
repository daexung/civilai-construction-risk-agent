"""Source-derived check for 2026 standard-estimate section 1-5-4."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity

spec_path = next(f for f in (ROOT / "data/drafts/specs").rglob("1-5-4.json")
                 if json.loads(f.read_text(encoding="utf-8"))["draft"]["quantity_model"]["name"] == "formula")
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
U = lambda value: json.loads('"' + value + '"')
fixture = {"work_type": U("\\uC2E0\\uCD95"), "building_use": U("\\uC8FC\\uAC70\\uC6A9"),
           "structure_type": U("\\uB2E8\\uB3C5\\uC8FC\\uD0DD"), "area": 100,
           "pile_construction": False, "wheel_washing_facility": 0}
result = formula_quantity(spec, fixture)
assert result["status"] == "computed", result
lines = {line["name"]: line for line in result["unit_lines"]}
expected = {
    U("\\uD3D0\\n\\uCF58\\uD06C\\uB9AC\\uD2B8\\uB958").replace("\n", ""): "3.2",
    U("\\uD3D0\\n\\uBCF4\\uB4DC\\uB958").replace("\n", ""): "0.051",
    U("\\uD3D0\\n\\uBAA9\\uC7AC\\uB958").replace("\n", ""): "0.3",
    U("\\uD3D0\\uD569\\uC131\\n\\uC218\\uC9C0\\uB958").replace("\n", ""): "0.174",
    U("\\uD63C\\uD569\\n\\uD3D0\\uAE30\\uBB3C").replace("\n", ""): "0.653",
}
assert {name: line["exact"] for name, line in lines.items()} == expected, lines
assert all(line["unit"] == "ton" and line["citations"] for line in lines.values()), lines
# The original p. 32 marks new-construction metal waste as a dash. Preserve it
# as an excluded source cell, never as a calculated numeric zero.
assert len(result["excluded_source_cells"]) == 1, result.get("excluded_source_cells")
assert result["excluded_source_cells"][0]["source_value"] == "-"

demolition = formula_quantity(spec, {**fixture, "work_type": U("\\uD574\\uCCB4")})
assert demolition["status"] == "blocked", demolition  # source says use design documents first
invalid_combination = formula_quantity(spec, {**fixture, "building_use": U("\\uBE44\\uC8FC\\uAC70\\uC6A9")})
assert invalid_combination["status"] == "blocked", invalid_combination
pile = formula_quantity(spec, {**fixture, "pile_construction": True})
assert pile["status"] == "blocked", pile
wheel = formula_quantity(spec, {**fixture, "wheel_washing_facility": 1})
assert wheel["status"] == "blocked", wheel

print("1-5-4 source-rate checks passed: all numeric waste quantities, dash omission, source applicability, and scope blocks")
