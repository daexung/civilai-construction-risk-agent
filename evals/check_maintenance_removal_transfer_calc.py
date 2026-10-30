"""Source-derived check for 2026 standard-estimate maintenance section 4-1-7."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.formula import formula_quantity

spec_path = next((ROOT / "data/drafts/specs").rglob("4-1-7.json"))
spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
equipment = next(field["allowed_values"][0] for field in spec["inputs"]
                 if field["name"] == "equipment_type")
work_types = next(field["allowed_values"] for field in spec["inputs"]
                  if field["name"] == "work_type")
base = {"equipment_type": equipment, "base_labor": 100,
        "is_special_equipment": False, "is_prior_item": False, "is_item_6": False}

# PDF pp. 923-924: device class row uses 80%, 60%, and 160%.
for work_type, expected in zip(work_types[:3], (80, 60, 160)):
    result = formula_quantity(spec, {**base, "work_type": work_type})
    assert result["status"] == "computed", result
    line = result["unit_lines"][0]
    assert line["exact"] == str(expected) and line["unit"] == "인", line
    assert line["citations"][0]["value"] in {"80", "60", "160"}

# Nonadjacent relocation is installation (100%) plus removal with reuse (80%).
relocation = formula_quantity(spec, {**base, "work_type": work_types[3]})
assert relocation["status"] == "computed", relocation
assert relocation["unit_lines"][0]["exact"] == "180", relocation

# Note ⑥ lists separate installation clauses whose removal, without reuse,
# is 50% of installation. Other combinations are not stated and remain blocked.
special = formula_quantity(spec, {**base, "work_type": work_types[1], "is_item_6": True})
assert special["status"] == "computed" and special["unit_lines"][0]["exact"] == "50", special
unsupported_special = formula_quantity(spec, {**base, "work_type": work_types[0], "is_item_6": True})
assert unsupported_special["status"] == "blocked", unsupported_special
excluded_equipment = formula_quantity(spec, {**base, "work_type": work_types[0],
                                             "is_special_equipment": True})
assert excluded_equipment["status"] == "blocked", excluded_equipment
prior_specific_item = formula_quantity(spec, {**base, "work_type": work_types[0],
                                               "is_prior_item": True})
assert prior_specific_item["status"] == "blocked", prior_specific_item

print("4-1-7 source-rate checks passed: three table rates, relocation sum, listed-item rule, and scope blocks")
