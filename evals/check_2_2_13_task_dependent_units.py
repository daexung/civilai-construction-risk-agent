from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/유지관리/2-2-13.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-2-2-13-task-dependent-units-audit-2026-10-19.json"
PACKAGE = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
SPEC = PACKAGE["draft"]


def check(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        raise SystemExit(1)


# Independent transcription of the selected original cells, checked visually
# against physical PDF pages 955–956 (printed pages 899–900).
expected_cells = {
    "p955-t2": {"궤도공": {"수량": "0.09"}, "특별인부": {"수량": "0.05"}, "보통인부": {"수량": "0.20"}},
    "p956-t0": {
        "궤도공": {"수량 판넬설치(개당)": "0.05", "수량 가받침 해체 및 설치(m당)": "0.09"},
        "특별인부": {"수량 판넬설치(개당)": "0.09", "수량 가받침 해체 및 설치(m당)": "0.18"},
        "보통인부": {"수량 판넬설치(개당)": "0.05", "수량 가받침 해체 및 설치(m당)": "0.09"},
    },
    "p956-t1": {"궤도공": {"수량": "0.11"}, "보통인부": {"수량": "0.25"}},
}
tables = {t["id"]: t for t in SPEC["tables"]}
for table_id, rows in expected_cells.items():
    for row, columns in rows.items():
        for column, value in columns.items():
            check(tables[table_id]["values"].get(row, {}).get(column) == value,
                  f"source cell {table_id}/{row}/{column} = {value}")

cases = [
    ({"work_type": "가받침 설치", "quantity": "10", "is_curve_under_950": False},
     {("궤도공", None): Fraction("0.09"), ("특별인부", None): Fraction("0.05"), ("보통인부", None): Fraction("0.20")}),
    ({"work_type": "판넬설치", "panel_type": "B2S A형", "quantity": "20", "support_length": "10", "is_curve_under_950": False},
     {("궤도공", None): Fraction("0.05"), ("특별인부", None): Fraction("0.09"), ("보통인부", None): Fraction("0.05"),
      ("궤도공", "support_length"): Fraction("0.09"), ("특별인부", "support_length"): Fraction("0.18"), ("보통인부", "support_length"): Fraction("0.09")}),
    ({"work_type": "판넬설치", "panel_type": "C형", "quantity": "20", "support_length": "10", "is_curve_under_950": False},
     {("궤도공", None): Fraction("0.025"), ("특별인부", None): Fraction("0.045"), ("보통인부", None): Fraction("0.025"),
      ("궤도공", "support_length"): Fraction("0.09"), ("특별인부", "support_length"): Fraction("0.18"), ("보통인부", "support_length"): Fraction("0.09")}),
    ({"work_type": "타설 후 정리작업", "quantity": "10", "is_curve_under_950": False},
     {("궤도공", None): Fraction("0.11"), ("보통인부", None): Fraction("0.25")}),
]
for inputs, expected in cases:
    result = per_unit(SPEC, inputs)
    check(result.get("status") == "computed", f"route computes for {inputs['work_type']}: {result.get('reason')}")
    actual = {(line["name"], line.get("quantity_input")): Fraction(line["exact"])
              for line in result["unit_lines"]}
    check(actual == expected, f"independent unit rates for {inputs['work_type']} / {inputs.get('panel_type', '-')}")
    totals = {}
    for line in result["unit_lines"]:
        qname = line.get("quantity_input") or "quantity"
        totals[line["name"]] = totals.get(line["name"], Fraction(0)) + Fraction(line["exact"]) * Fraction(inputs[qname])
    expected_totals = {
        "가받침 설치": {"궤도공": Fraction("0.9"), "특별인부": Fraction("0.5"), "보통인부": Fraction("2.0")},
        "타설 후 정리작업": {"궤도공": Fraction("1.1"), "보통인부": Fraction("2.5")},
    }.get(inputs["work_type"])
    if inputs["work_type"] == "판넬설치":
        expected_totals = ({"궤도공": Fraction("1.9"), "특별인부": Fraction("3.6"), "보통인부": Fraction("1.9")}
                           if inputs["panel_type"] in ("B2S A형", "B2S B형") else
                           {"궤도공": Fraction("1.4"), "특별인부": Fraction("2.7"), "보통인부": Fraction("1.4")})
    check(totals == expected_totals, f"independent quantity × rate totals for {inputs['work_type']} / {inputs.get('panel_type', '-')}")
    check(all(any(c.get("internal_id") == line["source"].split()[0] for c in line["citations"])
              for line in result["unit_lines"]), "each result line retains source table citation")

# C형’s 50% applies only to the panel-install rates; secondary m-based support
# rates remain unchanged. The 5%-within-which rule is not assigned a value.
curve = per_unit(SPEC, {"work_type": "판넬설치", "panel_type": "C형", "quantity": "20",
                        "support_length": "10", "is_curve_under_950": True})
check(curve.get("status") == "blocked", "uncertain curve surcharge stays blocked")
price_inputs = cases[1][0]
priced_quantity = per_unit(SPEC, price_inputs)
priced = price_unit(SPEC, priced_quantity["unit_lines"], select_rate_version("2026-10-19"),
                    price_inputs, "2026-10-19")
check(priced.get("status") in ("OK", "PARTIAL"), "offline wage pricing completes or preserves explicit gaps")
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
check(validation["ok"], "draft format and source citations validate")

audit = {
    "id": SPEC["id"], "status": "pass", "physical_pages": [955, 956], "printed_pages": [899, 900],
    "independently_checked_table_cells": sum(len(cols) for rows in expected_cells.values() for cols in rows.values()),
    "routes": len(cases), "source_rule_checks": ["C형 panel-install-only multiplier 0.5", "curve range kept blocked"],
    "offline_price_status": priced.get("status"), "draft_validation": "pass",
    "visual_original_pages": ["evals/runtime_validation/source-p955-track-replacement.png",
                              "evals/runtime_validation/source-p956-track-replacement.png"],
    "all_rules_fully_verified": False,
    "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
    "runtime_sha256": hashlib.sha256((ROOT / "backend/agent/tools/calc/per_unit.py").read_bytes()).hexdigest(),
}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: audit[k] for k in ("id", "independently_checked_table_cells", "routes", "offline_price_status", "draft_validation")}, ensure_ascii=True))
