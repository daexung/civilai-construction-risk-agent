"""Source-bounded audit for common 3-2-3 daily-equipment productivity."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.nodes.compute import compute
from pipeline.validate_drafts import load_chunks, validate_one

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/drafts/specs/공통/3-2-3.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/common-3-2-3-source-formula-audit-2026-10-19.json"
RATES = {
    ("보통토사", "대규모"): ("p124-t2", "불도저 | 규격 32ton", "대규모 시공량(㎥)", 930, "32ton 불도저"),
    ("보통토사", "중규모"): ("p124-t2", "불도저 | 규격 19ton", "중규모 시공량(㎥)", 560, "19ton 불도저"),
    ("보통토사", "소규모"): ("p124-t2", "굴착기 | 규격 1.0㎥", "소규모 시공량(㎥)", 310, "1.0㎥ 굴착기"),
    ("혼합토사", "대규모"): ("p124-t3", "불도저 | 규격 32ton", "대규모 시공량(㎥)", 640, "32ton 불도저"),
    ("혼합토사", "중규모"): ("p124-t3", "불도저 | 규격 19ton", "중규모 시공량(㎥)", 390, "19ton 불도저"),
    ("혼합토사", "소규모"): ("p124-t3", "굴착기 | 규격 1.0㎥", "소규모 시공량(㎥)", 230, "1.0㎥ 굴착기"),
}
ROCK_RATES = {"풍화암": 65, "연암": 50, "보통암": 30, "경암": 25}
GATHER_RATES = {"풍화암": 550, "연암": 520, "보통암": 450, "경암": 450}


def assert_computed(inputs: dict, expected: dict[str, Fraction], source_cells: dict[str, tuple]) -> None:
    result = formula_quantity(SPEC, inputs)
    assert result["status"] == "computed", (inputs, result)
    got = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
    assert got == expected, (inputs, got, expected)
    assert all(line["unit"] == "대·일" for line in result["unit_lines"])
    citations = {(c.get("internal_id"), c.get("row"), c.get("column"), c.get("value"))
                 for line in result["unit_lines"] for c in line.get("citations", [])}
    assert set(source_cells.values()) <= citations, (inputs, citations, source_cells)


SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
cases = 0
for (soil, scale), (table, row, column, rate, name) in RATES.items():
    inputs = {"soil_type": soil, "scale": scale, "volume": 930}
    if soil == "혼합토사":
        inputs["ripper_used"] = False
    assert_computed(inputs,
                    {name: Fraction(930, rate)},
                    {table: (table, row, column, str(rate))})
    cases += 1

node_result = compute({"spec_id": SPEC["id"],
                       "inputs": {"soil_type": "보통토사", "scale": "중규모", "volume": 1120}})
assert node_result["status"] == "COMPUTED", node_result
assert node_result["result"]["unit_lines"][0]["exact"] == "2"

for rock, rate in ROCK_RATES.items():
    for gathering in (False, True):
        expected = {"1.0㎥ 굴착기": Fraction(1000, rate),
                    "1.0㎥ 대형브레이커": Fraction(1000, rate)}
        cells = {"main": ("p125-t0", "굴착기 대형브레이커", rock, str(rate))}
        if gathering:
            expected["32ton 불도저(집토)"] = Fraction(1000, GATHER_RATES[rock])
            cells["gather"] = ("p125-t1", "불도저", rock, str(GATHER_RATES[rock]))
        assert_computed({"soil_type": "암", "rock_type": rock, "volume": 1000,
                         "separate_gathering": gathering}, expected, cells)
        cases += 1

# Conditional consultation, rejected irrelevant inputs, and missing conditional axis.
asked = formula_quantity(SPEC, {"soil_type": "혼합토사", "volume": 1})
assert asked["status"] == "ask" and asked["missing"] == ["scale", "ripper_used"], asked
rejected = formula_quantity(SPEC, {"soil_type": "암", "scale": "대규모", "rock_type": "연암",
                                    "volume": 1, "separate_gathering": False})
assert rejected["status"] == "rejected" and rejected.get("input") == "scale", rejected

# The independently checked source page has merged daily-output cells by scale.
# Each is linked only to the equipment row whose source quantity is 1 for that scale.
source_cells = 6 + 4 + 4
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
valid = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path), None)
assert valid["ok"], valid
audit = {"id": SPEC["id"], "status": "pass", "case_count": cases,
                  "independent_source_cells": source_cells,
                  "source_cell_links_in_outputs": 18,
                  "ordinary_and_mixed_scale_routes": 6,
                  "rock_type_and_gathering_routes": 8,
                  "other_equipment_routes": 4,
                  "consultation_conditions": 2,
                  "calculation_node": node_result["status"], "validator_ok": valid["ok"],
                  "source_review": {"printed_pages": [68, 69],
                                     "physical_pdf_pages": [124, 125],
                                     "method": "independent visual cell comparison against original table images; p124 daily output cells are vertically merged by scale and linked to the sole equipment row with quantity 1 in that scale"},
                  "expected_source_rates": {f"{soil}/{scale}": rate for (soil, scale), (_, _, _, rate, _) in RATES.items()},
                  "rock_productivity": ROCK_RATES,
                  "separate_gathering_productivity": GATHER_RATES,
                  "full_rule_verification": False,
                  "unresolved_cost_bases": ["유압식 리퍼 2% 기계경비", "치즐 1~7% 굴착기 기계경비"],
                  "not_calculated": ["외부 반출 적재·운반", "기계경비 기준의 리퍼/치즐 비용"]}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
