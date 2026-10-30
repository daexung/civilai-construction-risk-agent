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

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-6-17.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-13-6-17-inspection-share-audit-2026-10-19.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]


def check(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        raise SystemExit(1)


# Independent transcription from the original physical PDF page 878,
# printed page 822. The final inspection row explicitly states 7% of labor.
source_rows = [
    ("기술관리", "기계기사", "1.6"), ("재료절단사도", "제도공", "0.5"),
    ("현도", "현도공", "0.2"), ("괘서", "마킹공", "1.3"),
    ("절단", "절단공", "0.28"), ("교정", "플랜트제관공", "0.5"),
    ("단재가공괘서", "마킹공", "1.3"), ("절단", "산소절단공", "0.14"),
    ("Edge 가공", "산소절단공", "0.14"), ("용접", "플랜트용접공", "1.0"),
    ("교정", "플랜트제관공", "0.75"), ("Holing", "플랜트제관공", "0.37"),
    ("부분조립취부조정", "플랜트기계설치공", "2.5"), ("용접", "플랜트용접공", "6.8"),
    ("절단", "산소절단공", "0.08"), ("부분조립수정", "플랜트제관공", "1.75"),
    ("Grinding", "플랜트제관공", "1.5"), ("Grinding", "연마공(기계)", "0.13"),
    ("가조립조립", "플랜트기계설치공", "2.0"), ("해체", "플랜트기계설치공", "1.0"),
    ("도장준비", "플랜트제관공", "2.26"), ("도장", "도장공", "0.49"),
    ("운반조작", "특수비계공", "3.3"), ("동력조작", "플랜트전공", "0.66"),
    ("보조", "특별인부", "14.3"),
]
table = next(t for t in SPEC["tables"] if t["id"] == "p878-t0")
expected_rates = {}
row_names = {
    ("교정", "플랜트제관공", "0.5"): "교정(1) · 플랜트제관공",
    ("교정", "플랜트제관공", "0.75"): "교정(2) · 플랜트제관공",
    ("용접", "플랜트용접공", "1.0"): "용접(1) · 플랜트용접공",
    ("용접", "플랜트용접공", "6.8"): "용접(2) · 플랜트용접공",
    ("절단", "산소절단공", "0.14"): "절단(1) · 산소절단공",
    ("절단", "산소절단공", "0.08"): "절단(2) · 산소절단공",
}
for task, trade, value in source_rows:
    row = row_names.get((task, trade, value), f"{task} · {trade}")
    expected_rates[row] = Fraction(value)
    check(table["values"].get(row, {}).get("수량") == value,
          f"source rate cell p878/{task}/{trade} = {value}")
check(table["values"].get("검사 · 인력품의 7%", {}).get("수량") == "7%",
      "source inspection row is retained as a 7% rule, not a numeric cell")
base_total = sum(expected_rates.values(), Fraction(0))
expected_rates["검사 · 인력품의"] = base_total * Fraction(7, 100)

routes = []
for tonnage in ("1", "3"):
    result = per_unit(SPEC, {"quantity": str(tonnage)})
    check(result.get("status") == "computed" and len(result.get("unit_lines", [])) == 26,
          f"25 process rows plus separate inspection share calculate at {tonnage} ton: {result.get('reason')}")
    by_source = {}
    for line in result["unit_lines"]:
        source = next((c for c in line["citations"] if c.get("section_no") == "13-6-17"), None)
        check(source is not None and source.get("pdf_page") == 878,
              f"line cites original p.878 source for {line['name']}")
        row = source["row"]
        value = Fraction(line["exact"])
        by_source[row] = value
        check(value == expected_rates[row], f"independent rate/share arithmetic for source row {row}")
    check(by_source == expected_rates, f"all 25 rows and separate 7% inspection share at {tonnage} ton")
    routes.append({"quantity_ton": tonnage, "process_rows": 25, "base_labor_rate_total": str(base_total),
                   "inspection_share_rate": str(expected_rates["검사 · 인력품의"]),
                   "total_quantity_scaled": str(sum(by_source.values(), Fraction(0)) * Fraction(tonnage))})

price_inputs = {"quantity": "3"}
quantity = per_unit(SPEC, price_inputs)
priced = price_unit(SPEC, quantity["unit_lines"], select_rate_version("2026-10-19"),
                    price_inputs, "2026-10-19")
check(priced.get("status") in ("OK", "PARTIAL"), "offline wage pricing keeps missing wage mappings explicit")
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
check(validation["ok"], "draft format and table citations validate")

audit = {
    "id": SPEC["id"], "status": "pass", "physical_page": 878, "printed_page": 822,
    "independently_checked_numeric_source_cells": len(source_rows), "source_percentage_rule_checks": 1,
    "routes": routes, "offline_price_status": priced.get("status"), "draft_validation": "pass",
    "visual_original_page": "evals/runtime_validation/source-p878-tainter-guide.png",
    "consumables": "kept separate; D/M-based heavy-oil quantity and unit prices remain open",
    "all_rules_fully_verified": False,
    "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
    "runtime_sha256": hashlib.sha256((ROOT / "backend/agent/tools/calc/per_unit.py").read_bytes()).hexdigest(),
}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: audit[k] for k in ("id", "independently_checked_numeric_source_cells", "source_percentage_rule_checks", "offline_price_status", "draft_validation")}, ensure_ascii=True))
