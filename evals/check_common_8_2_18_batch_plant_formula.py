"""Focused source and formula audit for common 8-2-18 concrete batch plant."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/drafts/specs/공통/8-2-18.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/common-8-2-18-source-formula-audit-2026-10-19.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
DRAFT = SPEC["draft"]
CAPACITY = {
    "60㎥/h (96㎾)": ("1.0", "0.75"), "90㎥/h (144㎾)": ("1.5", "1.13"),
    "120㎥/h (160㎾)": ("2", "1.5"), "150㎥/h (177㎾)": ("2.5", "1.88"),
    "180㎥/h (213㎾)": ("3.0", "2.25"), "210㎥/h (233㎾)": ("3.5", "2.63"),
}
EFFICIENCY = {
    "양호": {"도로포장": "0.90", "교량": "0.50", "터널": "0.75", "사방": "0.85"},
    "보통": {"도로포장": "0.70", "교량": "0.45", "터널": "0.65", "사방": "0.75"},
    "불량": {"도로포장": "0.50", "교량": "0.40", "터널": "0.55", "사방": "0.65"},
}
WORKS = ("도로포장", "교량", "터널", "사방")


def check(inputs: dict, expected_status: str) -> dict:
    result = formula_quantity(DRAFT, inputs)
    assert result["status"] == expected_status, (inputs, result)
    return result


def expected_line(result: dict, value: Fraction, cells: set[tuple]) -> None:
    lines = result.get("unit_lines", [])
    assert len(lines) == 1 and lines[0]["unit"] == "hr", result
    assert Fraction(lines[0]["exact"]) == value, (lines[0], value)
    cites = {(cite.get("internal_id"), cite.get("row"), cite.get("column"), cite.get("value"))
             for cite in lines[0].get("citations", [])}
    assert cells <= cites, (cells, cites)


computed = blocked = 0
for slump in ("5㎝이상", "5㎝미만"):
    for capacity, q_pair in CAPACITY.items():
        q = Fraction(q_pair[0 if slump == "5㎝이상" else 1])
        for work in WORKS:
            for site, e_by_work in EFFICIENCY.items():
                modes = [(False, None)] if work != "터널" else [(False, None), (True, False), (True, True)]
                for shotcrete, fiber in modes:
                    inputs = {"slump": slump, "spec": capacity, "work_type": work,
                              "site_condition": site, "quantity": 1000}
                    if work == "터널":
                        inputs["is_tunnel_shotcrete"] = shotcrete
                    if fiber is not None:
                        inputs["mix_steel_fiber"] = fiber
                    e = Fraction(e_by_work[work])
                    cycle = Fraction(5, 2) if shotcrete and fiber else Fraction(3, 2)
                    result = check(inputs, "computed")
                    exact_hours = Fraction(1000) * cycle / (60 * q * e)
                    source_cells = {
                        ("p251-t0", slump, capacity, q_pair[0 if slump == "5㎝이상" else 1]),
                        ("p251-t1", site, work, e_by_work[work]),
                    }
                    cites = {(c.get("internal_id"), c.get("row"), c.get("column"), c.get("value"))
                             for c in result["unit_lines"][0].get("citations", [])}
                    # Citations are checked by exact table cell IDs/axes; cycle-time notes are checked separately.
                    assert source_cells <= cites, (inputs, source_cells, cites)
                    assert Fraction(result["unit_lines"][0]["exact"]) == exact_hours
                    assert any(c.get("internal_id") == "p250-x13" for c in result["unit_lines"][0]["citations"])
                    if shotcrete and fiber:
                        assert any("2.5분" in (c.get("quote") or "") for c in result["unit_lines"][0]["citations"])
                    computed += 1

            # Very poor is a source-backed literal only for tunnel shotcrete.
            for shotcrete, fiber in ([(False, None)] if work != "터널" else [(False, None), (True, False), (True, True)]):
                inputs = {"slump": slump, "spec": capacity, "work_type": work,
                          "site_condition": "매우 불량", "quantity": 1000}
                if work == "터널":
                    inputs["is_tunnel_shotcrete"] = shotcrete
                if fiber is not None:
                    inputs["mix_steel_fiber"] = fiber
                if work != "터널" or not shotcrete:
                    result = check(inputs, "blocked")
                    blocked += 1
                    continue
                result = check(inputs, "computed")
                q = Fraction(q_pair[0 if slump == "5㎝이상" else 1])
                cycle = Fraction(5, 2) if fiber else Fraction(3, 2)
                assert Fraction(result["unit_lines"][0]["exact"]) == Fraction(1000) * cycle / (60 * q * Fraction(2, 5))
                assert any(c.get("internal_id") == "p251-x8" for c in result["unit_lines"][0]["citations"])
                computed += 1

assert computed == 240 and blocked == 48, (computed, blocked)
asked = check({"work_type": "터널", "quantity": 1000}, "ask")
assert set(asked["missing"]) >= {"is_tunnel_shotcrete", "slump", "spec", "site_condition"}
irrelevant = formula_quantity(DRAFT, {"slump":"5㎝이상","spec":"60㎥/h (96㎾)","work_type":"도로포장",
                                      "site_condition":"양호","quantity":1,"is_tunnel_shotcrete":True})
assert irrelevant["status"] == "rejected" and irrelevant.get("input") == "is_tunnel_shotcrete", irrelevant
node_status = "not_registered_in_active_execution_index"
if DRAFT["id"] in load_specs():
    node_result = compute({"spec_id": DRAFT["id"], "inputs": {"slump":"5㎝이상","spec":"60㎥/h (96㎾)",
                                                                  "work_type":"도로포장","site_condition":"양호",
                                                                  "quantity":60}})
    assert node_result["status"] == "COMPUTED", node_result
    assert node_result["result"]["unit_lines"][0]["exact"] == "5/3"
    node_status = node_result["status"]

validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
assert validation["ok"], validation
audit = {"id": DRAFT["id"], "status": "pass", "combinations_checked": computed + blocked,
         "computed_combinations": computed, "blocked_combinations": blocked,
         "independent_numeric_source_cells": 24,
         "source_pages_reviewed": {"printed": [194, 195], "physical_pdf": [250, 251]},
         "source_method": "Original p250/p251 images checked; 12 mixer-volume cells, 12 work-efficiency cells, exact headers and condition notes independently matched.",
         "formula": "Q=60×q×E/cm; runtime_hours=quantity×cm/(60×q×E)",
         "special_rules": {"base_cycle_min": "1.5", "tunnel_shotcrete_fiber_cycle_min": "2.5",
                           "tunnel_shotcrete_very_poor_efficiency": "0.40"},
         "full_rule_verification": False, "calculation_node": node_status,
         "validator_ok": validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
