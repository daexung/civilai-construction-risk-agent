"""Source-derived check for 2026 standard-estimate section 1-1-4."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity

U = lambda value: json.loads('"' + value + '"')
spec_path = next((ROOT / "data/drafts/specs").rglob("1-1-4.json"))
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
result = formula_quantity(spec, {
    "base_welding_labor": 3,
    "total_steel_weight": 500,
    "welding_method": U("\\uBC18\\uC790\\uB3D9\\uC6A9\\uC811"),
    "welding_length": 100,
})
assert result["status"] == "computed", result
lines = {line["name"]: line for line in result["unit_lines"]}
# Source pp. 569-570: 500 t selects 0.99; 3 × 0.99 = 2.97 person-days.
assert lines[U("\\uC6A9\\uC811\\uACF5\\uC218")]["exact"] == "2.97", lines
# Source p. 570: semi-automatic welding consumes 0.23 kg wire and
# 0.12 kg gas per metre; 100 m therefore yields 23 kg and 12 kg.
assert lines[U("CO2 \\uC640\\uC774\\uC5B4")]["exact"] == "23", lines
assert lines[U("\\uD0C4\\uC0B0\\uAC00\\uC2A4")]["exact"] == "12", lines
assert lines[U("CO2 \\uC640\\uC774\\uC5B4")]["unit"] == U("\\u338F")
assert len(result["excluded_source_cells"]) == 3
assert all(item["source_value"] == "-" for item in result["excluded_source_cells"])
assert all(item["citations"] for item in result["excluded_source_cells"])

print("1-1-4 source-rate checks passed: weight band, labor correction, material rates, and source dash exclusions")
