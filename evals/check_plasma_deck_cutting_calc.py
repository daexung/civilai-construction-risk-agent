"""Source-derived check for 2026 standard-estimate section 1-3-2."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit

spec_path = next((ROOT / "data/drafts/specs").rglob("1-3-2.json"))
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
result = per_unit(spec, {"length": 100})
assert result["status"] == "computed", result
lines = {line["name"]: line for line in result["unit_lines"]}
# PDF p. 575 states 0.05 and 0.02 person per 10 m. Convert those
# source rates to per metre, then independently multiply by the 100 m fixture.
assert Fraction(lines["철골공"]["exact"]) * 100 == Fraction(1, 2), lines
assert Fraction(lines["특별인부"]["exact"]) * 100 == Fraction(1, 5), lines
assert lines["철골공"]["citations"][0]["value"] == "0.05"
assert lines["특별인부"]["citations"][0]["value"] == "0.02"
assert "10%" in spec["cost_rules"][0]["rate"] or spec["cost_rules"][0]["rate"] == "0.10"

print("1-3-2 source-rate checks passed: both trade totals, per-10m conversion, and cited source cells")
