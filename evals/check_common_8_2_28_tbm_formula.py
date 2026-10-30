"""Source-backed bounded formula audit for common 8-2-28 TBM productivity."""
from __future__ import annotations

import json
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from backend.agent.tools.calc.formula import formula_quantity
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/drafts/specs/공통/8-2-28.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/common-8-2-28-tbm-source-formula-audit-2026-10-19.json"
DOC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SPEC = DOC["draft"]
PI50 = Decimal("3.14159265358979323846264338327950288419716939937510")


def source_expected(inputs: dict) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 70
        d = Decimal(str(inputs["excavation_diameter"]))
        length = Decimal(str(inputs["stroke_length"]))
        rpm = Decimal(str(inputs["rotation_speed"]))
        pe = Decimal(str(inputs["penetration_depth"]))
        quantity = Decimal(str(inputs["quantity"]))
        efficiency = {"양호": Decimal("0.75"), "보통": Decimal("0.65"), "불량": Decimal("0.55")}[inputs["efficiency_condition"]]
        area = PI50 * d * d / Decimal(4)
        cycle = length / (rpm * pe) * Decimal(100) + Decimal(10)
        return quantity * cycle / (Decimal(60) * area * length * efficiency)


computed = 0
for diameter in ("3.0", "4.5", "6.0"):
    for length in ("0.8", "1.2"):
        for rpm in ("2", "3.5"):
            for pe in ("1.0", "1.5"):
                for efficiency in ("양호", "보통", "불량"):
                    for quantity in ("250", "1000"):
                        inputs = {"excavation_diameter": diameter, "stroke_length": length,
                                  "rotation_speed": rpm, "penetration_depth": pe,
                                  "efficiency_condition": efficiency, "quantity": quantity,
                                  "composition_varies": False}
                        result = formula_quantity(SPEC, inputs)
                        assert result["status"] == "computed", (inputs, result)
                        line = result["unit_lines"][0]
                        assert line["name"] == "터널전단면 굴착기 작업시간" and line["unit"] == "hr"
                        with localcontext() as ctx:
                            ctx.prec = 70
                            actual = Decimal(Fraction(line["exact"]).numerator) / Decimal(Fraction(line["exact"]).denominator)
                            assert abs(actual - source_expected(inputs)) < Decimal("1e-40"), (inputs, actual)
                        citations = line.get("citations", [])
                        assert any(c.get("internal_id") == "p274-t0" and c.get("value") == {"양호": "0.75", "보통": "0.65", "불량": "0.55"}[efficiency] for c in citations)
                        assert any(c.get("internal_id") == "p274-x2" for c in citations)
                        assert any(c.get("internal_id") == "p274-x10" for c in citations)
                        assert any(c.get("internal_id") == "p273-x17" for c in citations)
                        assert any(c.get("internal_id") == "p274-x3" for c in citations)
                        assert any(c.get("internal_id") == "p274-x6" for c in citations)
                        computed += 1

blocked = formula_quantity(SPEC, {"excavation_diameter":"4.5","stroke_length":"1.2","rotation_speed":"3.5",
                                   "penetration_depth":"1.5","efficiency_condition":"양호","quantity":"1000",
                                   "composition_varies":True})
assert blocked["status"] == "blocked", blocked

missing = formula_quantity(SPEC, {"excavation_diameter":"4.5","stroke_length":"1.2","rotation_speed":"3.5",
                                  "penetration_depth":"1.5","efficiency_condition":"양호","quantity":"1000"})
assert missing["status"] == "ask" and "composition_varies" in missing["missing"], missing

node_status = "not_registered_in_active_execution_index"
ident = SPEC["id"]
if ident in load_specs():
    node_result = compute({"spec_id": ident, "inputs": {"excavation_diameter":"4.5","stroke_length":"1.2",
                                  "rotation_speed":"3.5","penetration_depth":"1.5",
                                  "efficiency_condition":"양호","quantity":"1000",
                                  "composition_varies":False}})
    assert node_result["status"] == "COMPUTED", node_result
    node_status = node_result["status"]

validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
assert validation["ok"], validation
audit = {"id": SPEC["id"], "status": "pass", "formula_cases": computed,
         "source_numeric_cells": 3, "formula_and_rule_citations_checked": 5,
         "source_pages_reviewed": {"printed": [217,218], "physical_pdf": [273,274]},
         "source_formula": "Q=60×A×ℓ×E/cm; A=πD²/4; cm=ℓ/(R×Pe)×100+10; operating_hours=quantity/Q",
         "pi_representation": "50-decimal rational constant; compared against independently evaluated 50-digit decimal π",
         "unresolved_source_policy": "E category is selected from source condition criteria; overlapping edges and conflicting indicators are not inferred. Composition variance requiring field-performance data is blocked.",
         "full_rule_verification": False, "calculation_node": node_status, "validator_ok": validation["ok"]}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(audit, ensure_ascii=False, indent=2))
