"""Source-derived check for 2026 standard-estimate section 1-2-7."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit

U = lambda value: json.loads('"' + value + '"')
spec_path = next((ROOT / "data/drafts/specs").rglob("1-2-7.json"))
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
common = {"quantity": 2, "is_standard_spec": True, "is_exterior_fixed": True}

# PDF p. 574: 42 person-days per crane for erection and dismantling;
# vertical movement is 6 person-days per move. Resource is special scaffolder.
expected = {
    "\\uAC00\\uC124": ("42", "\\uC778/\\uB300"),
    "\\uD574\\uCCB4\\uC815\\uBE44": ("42", "\\uC778/\\uB300"),
    "\\uC218\\uC9C1\\uC774\\uB3D9(1\\uD68C\\uB2F9)": ("6", "\\uC778/\\uD68C"),
}
for work_type, (rate, unit) in expected.items():
    result = per_unit(spec, {**common, "work_type": U(work_type)})
    assert result["status"] == "computed", result
    line = result["unit_lines"][0]
    assert line["name"] == U("\\uD2B9\\uC218\\uBE44\\uACC4\\uACF5"), line
    assert line["exact"] == rate and line["unit"] == U(unit), line
    assert line["citations"][0]["value"] == ("6.0" if rate == "6" else "42.0")

out_of_scope = per_unit(spec, {**common, "work_type": U("\\uAC00\\uC124"),
                               "is_standard_spec": False})
assert out_of_scope["status"] == "blocked", out_of_scope

print("1-2-7 source-rate checks passed: row-specific denominators, special trade, and source scope block")
