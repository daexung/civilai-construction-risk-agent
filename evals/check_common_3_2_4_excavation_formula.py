"""Focused offline audit for common 3-2-4 machine-excavation productivity."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import load_chunks, validate_one

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/drafts/specs/공통/3-2-4.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/common-3-2-4-source-formula-audit-2026-10-19.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
DRAFT = SPEC["draft"]
FORMULA = DRAFT["quantity_model"]["params"]["outputs"]

EARTH = {
    "보통토사": {"TypeⅠ": ("p125-t4", "굴착기 | 규격 1.0㎥", "TypeⅠ 시공량(㎥)", 560, "1.0㎥ 굴착기"),
                 "TypeⅡ": ("p125-t4", "굴착기 | 규격 1.0㎥", "TypeⅡ 시공량(㎥)", 420, "1.0㎥ 굴착기"),
                 "TypeⅢ": ("p125-t4", "굴착기 | 규격 0.6㎥", "TypeⅢ 시공량(㎥)", 190, "0.6㎥ 굴착기")},
    "혼합토사": {"TypeⅠ": ("p126-t0", "굴착기 | 규격 1.0㎥", "TypeⅠ 시공량(㎥)", 390, "1.0㎥ 굴착기"),
                 "TypeⅡ": ("p126-t0", "굴착기 | 규격 1.0㎥", "TypeⅡ 시공량(㎥)", 300, "1.0㎥ 굴착기"),
                 "TypeⅢ": ("p126-t0", "굴착기 | 규격 0.6㎥", "TypeⅢ 시공량(㎥)", 150, "0.6㎥ 굴착기")},
}
ROCK = {"풍화암": {"TypeⅠ": 38, "TypeⅡ": 35}, "연암": {"TypeⅠ": 30, "TypeⅡ": 28},
        "보통암": {"TypeⅠ": 22, "TypeⅡ": 19}, "경암": {"TypeⅠ": 16, "TypeⅡ": 14}}


def run(inputs: dict, status: str) -> dict:
    result = formula_quantity(DRAFT, inputs)
    assert result["status"] == status, (inputs, result)
    return result


def check_line_cites(result: dict, expected_cells: set[tuple]) -> None:
    lines = result.get("unit_lines", [])
    assert lines and all(line["unit"] == "대·일" for line in lines), result
    citations = {(cite.get("internal_id"), cite.get("row"), cite.get("column"), cite.get("value"))
                 for line in lines for cite in line.get("citations", [])}
    assert expected_cells <= citations, (expected_cells, citations)


computed = blocked = 0
independent_cells: set[tuple] = set()
for soil, routes in EARTH.items():
    for type_class, (table, row, column, rate, name) in routes.items():
        independent_cells.add((table, row, column, str(rate)))
        for water in (False, True):
            for depth in (False, True):
                inputs = {"soil_type": soil, "type_class": type_class, "water_issue": water,
                          "depth_over_5m": depth, "volume": 1000, "urban_narrow": False}
                if soil == "혼합토사":
                    inputs["ripper_used"] = False
                if water and depth:
                    run(inputs, "blocked")
                    blocked += 1
                    continue
                factor = Fraction(3, 4) if water else Fraction(91, 100) if depth else Fraction(1)
                expected = Fraction(1000, rate * factor)
                result = run(inputs, "computed")
                assert len(result["unit_lines"]) == 1
                assert Fraction(result["unit_lines"][0]["exact"]) == expected
                check_line_cites(result, {(table, row, column, str(rate))})
                if water:
                    assert any(c.get("internal_id") == "p126-t1" for c in result["unit_lines"][0]["citations"])
                if depth:
                    assert any(c.get("internal_id") == "p125-t4" for c in result["unit_lines"][0]["citations"])
                computed += 1

for rock, rates in ROCK.items():
    for type_class, rate in rates.items():
        independent_cells.add(("p126-t1", rock, type_class, str(rate)))
        for water in (False, True):
            result = run({"soil_type": "암", "rock_type": rock, "type_class": type_class,
                          "water_issue": water, "volume": 1000, "urban_narrow": False}, "computed")
            factor = Fraction(3, 4) if water else Fraction(1)
            expected = Fraction(1000, rate * factor)
            lines = result["unit_lines"]
            assert len(lines) == 2 and {line["name"] for line in lines} == {"1.0㎥ 굴착기", "1.0㎥ 대형브레이커"}
            assert all(Fraction(line["exact"]) == expected for line in lines)
            check_line_cites(result, {("p126-t1", rock, type_class, str(rate))})
            computed += 1
    for water in (False, True):
        run({"soil_type": "암", "rock_type": rock, "type_class": "TypeⅢ", "water_issue": water,
             "volume": 1000, "urban_narrow": False}, "blocked")
        blocked += 1

urban = run({"soil_type": "보통토사", "type_class": "TypeⅠ", "water_issue": False,
             "depth_over_5m": False, "volume": 10, "urban_narrow": True}, "blocked")
assert "8-2-3" in urban["reason"]
asked = run({"soil_type": "암", "volume": 1000}, "ask")
assert set(asked["missing"]) >= {"rock_type", "type_class", "water_issue", "urban_narrow"}
node_result = compute({"spec_id": DRAFT["id"], "inputs": {"soil_type": "보통토사", "type_class": "TypeⅠ",
                                                                  "water_issue": False, "depth_over_5m": False,
                                                                  "volume": 1120, "urban_narrow": False}})
assert node_result["status"] == "COMPUTED", node_result
assert node_result["result"]["unit_lines"][0]["exact"] == "2"

validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
assert validation["ok"], validation
assert len(FORMULA) == 50
audit = {"id": DRAFT["id"], "status": "pass", "combinations_checked": 48,
         "computed_combinations": computed, "blocked_combinations": blocked,
         "independent_numeric_source_cells": len(independent_cells),
         "source_cell_routes": len(FORMULA), "source_pages_reviewed": {"printed": [69, 70], "physical_pdf": [125, 126]},
         "source_method": "Original p125/p126 page images visually checked; source equipment quantity cells, Type headers and vertically merged daily-output cells mapped to their exact equipment rows.",
         "rate_factors": {"water_disruption": "0.75 of source productivity", "depth_over_5m": "0.91 of source productivity"},
         "combination_policy": "Water and depth reductions together are blocked because source does not state combination method.",
         "calculation_node": node_result["status"],
         "separate_rock_type_III": "blocked: no source productivity cell",
         "urban_narrow": "blocked and cited to common 8-2-3 rule",
         "full_rule_verification": False,
         "unresolved_cost_bases": ["ripper 2% of machine cost", "chisel 1-7% of excavator machine cost"],
         "not_calculated": ["external spoil haul/loading", "machine-cost based ripper/chisel price"],
         "validator_ok": validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
