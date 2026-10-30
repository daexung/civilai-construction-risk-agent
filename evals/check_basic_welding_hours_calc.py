"""Source-derived check for 2026 standard-estimate section 1-1-3."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit

U = lambda value: json.loads('"' + value + '"')
spec_path = next(Path("data/drafts/specs").glob("*/1-1-3.json"))
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]

def calculate(member, weld_type, thickness, length):
    return per_unit(spec, {
        "member_type": U(member), "weld_type": U(weld_type),
        "plate_thickness": thickness, "weld_length": length, "quantity": 1,
    })

# PDF 2026 pp. 569-570: 6 mm fillet coefficient .68, so 30 m/t gives
# 20.4 m/t equivalent length; the 20-or-more row is .37 person-day/t.
fillet = calculate("\\uC804\\uC6A9\\uC811\\uBD80\\uC7AC", "\\uD544\\uB9BF\\uC6A9\\uC811", 6, 30)
assert fillet["status"] == "computed", fillet
assert fillet["unit_lines"][0]["exact"] == "37/100", fillet
assert {c["value"] for c in fillet["unit_lines"][0]["citations"]} >= {"0.37", "0.68"}

# Source note: rolled H-section base labor is multiplied by .73.
rolled = calculate("H\\uD615\\uAC15\\uBD80\\uC7AC", "\\uD544\\uB9BF\\uC6A9\\uC811", 6, 30)
assert rolled["status"] == "computed", rolled
assert rolled["unit_lines"][0]["exact"] == "2701/10000", rolled

# V/K/X thickness 6 coefficient 2.86: 7 m/t -> equivalent 20.02 m/t.
vkw = calculate("\\uC804\\uC6A9\\uC811\\uBD80\\uC7AC", "V, K, X\\uC6A9\\uC811", 6, 7)
assert vkw["status"] == "computed" and vkw["unit_lines"][0]["exact"] == "37/100", vkw

# The source coefficient table starts at 5 mm for fillet welding.
outside = calculate("\\uC804\\uC6A9\\uC811\\uBD80\\uC7AC", "\\uD544\\uB9BF\\uC6A9\\uC811", 4, 30)
assert outside["status"] == "rejected", outside

print("1-1-3 source-rate checks passed: threshold, coefficient, rolled-section correction, and scope rejection")
