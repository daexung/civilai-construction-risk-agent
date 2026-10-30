"""Exact source route and rule checks for steel-pipe arc/TIG welding."""
from __future__ import annotations

import itertools
import json
import hashlib
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-2-3.json").read_text(encoding="utf-8"))["draft"]


def check(condition: bool, label: str) -> None:
    print(f"{'PASS' if condition else 'FAIL'} {label}")
    if not condition:
        raise SystemExit(1)


def run(method: str, diameter: str, sch: str, **overrides: object) -> dict:
    inputs = {"welding_method": method, "diameter": diameter, "sch_no": sch,
              "quantity": "10", "pipe_material": "탄소강관", "pressure_over_100": False,
              "ndt_ks1": False, "welding_condition": "일반",
              "pressure_test_or_calibration": False}
    inputs.update(overrides)
    return per_unit(SPEC, inputs, labor_only=True)


# Values below were read independently from the original rendered p.801-p.804 tables.
cases = [
    ("전기아크용접", "200", "20", {"용접공": Fraction("0.287")}, Fraction("0.600"), "p801-t1", "200"),
    ("전기아크용접", "400", "40", {"플랜트 용접공": Fraction("0.725")}, Fraction("3.390"), "p802-t0", "400"),
    ("TIG용접", "200", "20", {"플랜트 용접공": Fraction("0.244"), "특별인부": Fraction("0.143")}, None, "p803-t1", "200"),
    ("TIG용접", "600", "160", {"플랜트 용접공": Fraction("4.597"), "특별인부": Fraction("2.692")}, None, "p804-t0", "600"),
]
for method, diameter, sch, expected_labor, expected_material, table_id, row in cases:
    result = run(method, diameter, sch)
    check(result.get("status") == "computed", f"exact table route {method}/{diameter}/{sch}: {result.get('reason')}")
    lines = result["unit_lines"]
    labor = {line["name"]: Fraction(line["exact"]) for line in lines if line["kind"] == "labor"}
    check(labor == expected_labor, f"independent labor arithmetic {method}/{diameter}/{sch}")
    cite = next(c for line in lines if line["kind"] == "labor" for c in line["citations"]
                if c.get("internal_id") == table_id)
    check(cite["row"] == row and sch in cite["column"], f"exact row and SCH source citation {table_id}/{row}/{sch}")
    materials = [Fraction(line["exact"]) for line in lines if line["kind"] == "material"]
    if expected_material is None:
        check(not materials, f"no invented TIG material coefficients {diameter}/{sch}")
    else:
        check(materials == [expected_material], f"independent electrode quantity {diameter}/{sch}")

baseline = run("전기아크용접", "200", "20")
adjusted = run("전기아크용접", "200", "20", pressure_test_or_calibration=True)
base_labor = next(Fraction(x["exact"]) for x in baseline["unit_lines"] if x["kind"] == "labor")
adjusted_labor = next(Fraction(x["exact"]) for x in adjusted["unit_lines"] if x["kind"] == "labor")
check(adjusted_labor == base_labor * Fraction(105, 100), "source 5% rule only when hydraulic test/calibration applies")

for label, overrides in [
    ("alloy surcharge", {"pipe_material": "합금강관"}),
    ("KS 1 NDT range", {"ndt_ks1": True}),
    ("special weld up-to percentage", {"welding_condition": "Back Mirror"}),
    ("high-pressure TIG welder", {"welding_method": "TIG용접", "pressure_over_100": True}),
]:
    blocked = run("전기아크용접", "200", "20", **overrides)
    check(blocked.get("status") == "blocked", f"unresolved policy held: {label}")
blank = run("전기아크용접", "15", "20")
check(blank.get("status") == "blocked" and "no numeric source cell" in blank.get("reason", ""),
      "blank printed source intersection is held without zero/fuzzy fill")

# Exercise every exact diameter/method/SCH tuple through the calculator route resolver.
diameters = [str(x) for x in next(f for f in SPEC["inputs"] if f["name"] == "diameter")["allowed_values"]]
sch_values = [str(x) for x in next(f for f in SPEC["inputs"] if f["name"] == "sch_no")["allowed_values"]]
statuses = []
for method, diameter, sch in itertools.product(["전기아크용접", "TIG용접"], diameters, sch_values):
    result = run(method, diameter, sch)
    statuses.append(result.get("status"))
check(len(statuses) == 378, "all 378 declared method/diameter/SCH combinations exercised")
check(all(status in {"computed", "blocked"} for status in statuses),
      f"all combinations fail closed at exact source bounds; statuses={sorted(set(statuses))}")
check(Counter(statuses)["computed"] > 0 and Counter(statuses)["blocked"] > 0,
      "valid intersections compute while unprinted intersections remain held")

# Offline price check uses only the saved local wage snapshot; consumable price is absent.
price_inputs = {"welding_method": "전기아크용접", "sch_no": "20", "diameter": "200",
                "quantity": "10", "pipe_material": "탄소강관", "pressure_over_100": False,
                "ndt_ks1": False, "welding_condition": "일반",
                "pressure_test_or_calibration": False}
price_quantity = per_unit(SPEC, price_inputs, labor_only=True)
priced = price_unit(SPEC, price_quantity["unit_lines"], select_rate_version("2026-10-19"),
                    price_inputs, "2026-10-19")
check(priced.get("status") == "PARTIAL" and priced.get("total") == "84641",
      "offline wage pricing exact; consumable remains unpriced")

audit = {"id": "2026-정오표1차/기계설비/13-2-3/강관용접",
         "source_pages": [801, 802, 803, 804], "reconstructed_numeric_cells": 380,
         "independent_visual_cell_checks": 19,
         "exact_routed_cases": len(cases), "declared_method_diameter_sch_combinations": len(statuses),
         "combination_status_counts": dict(Counter(statuses)),
         "source_5_percent_case": {"base_person_days_per_joint": "0.287",
                                   "adjusted_person_days_per_joint": "0.30135"},
         "offline_price": {"status": priced.get("status"), "total": priced.get("total"),
                           "priced_labor": "82176.7", "unpriced_material": "용접봉"},
         "all_rules_fully_verified": False,
         "open_scope": ["TIG 용접봉·보호가스 coefficients", "equipment costs 3%",
                        "alloy surcharge reference", "NDT range", "welding-condition up-to rates",
                        "special TIG welder route"],
         "spec_sha256": hashlib.sha256((ROOT / "data/drafts/specs/기계설비/13-2-3.json").read_bytes()).hexdigest(),
         "runtime_sha256": hashlib.sha256((ROOT / "backend/agent/tools/calc/per_unit.py").read_bytes()).hexdigest()}
out = ROOT / "evals/runtime_validation/13-2-3-exact-source-route-audit-2026-10-19.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("13-2-3 exact source route audit complete; material and rule scope remains partial for TIG and cited open conditions.")
