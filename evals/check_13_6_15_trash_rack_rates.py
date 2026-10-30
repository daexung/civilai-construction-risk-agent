from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-6-15.json"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-13-6-15-trash-rack-rate-recovery-audit-2026-10-19.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]


def check(ok: bool, label: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok:
        raise SystemExit(1)


# Independently transcribed from rendered physical PDF pages 875 and 876
# (printed pages 819 and 820). Repeated occupation rows remain separate.
source_rows = [
    (875, "Holing", "플랜트제관공", "3.22"),
    (875, "Threading", "플랜트제관공", "4.3"),
    (875, "사도", "기계연마공", "18.66"),
    (875, "현도", "제도공", "0.3"),
    (875, "괘서", "현도공", "0.086"),
    (875, "교정", "마킹공", "2"),
    (875, "절단", "플랜트제관공", "0.5"),
    (875, "절단", "산소절단공", "0.656"),
    (875, "기술관리", "플랜트제관공", "36.902"),
    (875, "기술관리", "기계기사", "5.2"),
    (875, "제작정리", "플랜트제관공", "1.25"),
    (876, "용접", "플랜트용접공", "4.46"),
    (876, "교정", "플랜트제관공", "0.75"),
    (876, "조작", "특수비계공", "3.3"),
    (876, "소운반", "인부", "1"),
    (876, "보조(기능)", "특별인부", "37.68"),
]
tables = {t["id"]: t for t in SPEC["tables"]}
for page, task, trade, rate in source_rows:
    table = tables["p875-t2" if page == 875 else "p876-t0"]
    row = f"{task} · {trade}"
    check(table["values"].get(row, {}).get("수량") == rate,
          f"original rate cell p{page}/{task}/{trade} = {rate}")

expected = {f"{task} · {trade}": Fraction(rate) for _, task, trade, rate in source_rows}
routes = []
for tonnage in ("1", "2.5"):
    result = per_unit(SPEC, {"quantity": tonnage})
    check(result.get("status") == "computed" and len(result.get("unit_lines", [])) == 16,
          f"all 16 source process rows execute at {tonnage} ton: {result.get('reason')}")
    by_source = {}
    for line in result["unit_lines"]:
        source = next((c for c in line["citations"] if c.get("section_no") == "13-6-15"), None)
        check(source is not None and source.get("pdf_page") in (875, 876),
              f"row citation stays on original source page for {line['name']}")
        by_source[source["row"]] = Fraction(line["exact"])
    check(by_source == expected, f"independent original process-rate map at {tonnage} ton")
    labor_totals = defaultdict(Fraction)
    for page, task, trade, rate in source_rows:
        labor_totals[trade] += Fraction(rate) * Fraction(tonnage)
    routes.append({"quantity_ton": tonnage, "source_rows": len(by_source),
                   "quantity_scaled_labor_by_trade": {k: str(v) for k, v in sorted(labor_totals.items())}})

price_inputs = {"quantity": "2.5"}
result = per_unit(SPEC, price_inputs)
priced = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"),
                    price_inputs, "2026-10-19")
check(priced.get("status") in ("OK", "PARTIAL"), "offline labor pricing preserves missing catalog rates")
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
check(validation["ok"], "draft format and table citations validate")

audit = {
    "id": SPEC["id"], "status": "pass", "physical_pages": [875, 876], "printed_pages": [819, 820],
    "independently_checked_source_rate_cells": len(source_rows), "routes": routes,
    "offline_price_status": priced.get("status"), "draft_validation": "pass",
    "visually_checked_original_pages": ["evals/runtime_validation/source-p875-trash-rack-fab.png",
                                        "evals/runtime_validation/source-p876-trash-rack-fab.png"],
    "consumables": "kept outside labor total; separate unit-price information is incomplete",
    "all_rules_fully_verified": False,
    "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
    "runtime_sha256": hashlib.sha256((ROOT / "backend/agent/tools/calc/per_unit.py").read_bytes()).hexdigest(),
}
AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: audit[k] for k in ("id", "independently_checked_source_rate_cells", "offline_price_status", "draft_validation")}, ensure_ascii=True))
