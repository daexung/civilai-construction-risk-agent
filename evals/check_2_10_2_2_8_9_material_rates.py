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

CASES = {
    "2-10-2": {
        "path": ROOT / "data/drafts/specs/공통/2-10-2.json", "page": 115,
        "table": "p115-t3", "rows": {"방진망": ("㎡", Fraction("1.06")), "철선": ("kg", Fraction("0.115"))},
        "labor": Fraction("0.16"), "note_chunk": "p115-x12",
        "note_quote": "※ 위 재료량은 할증이 포함되어 있으며, 방진망의 손율은 1회사용 후 100%로 한다.",
    },
    "2-8-9": {
        "path": ROOT / "data/drafts/specs/공통/2-8-9.json", "page": 109,
        "table": "p109-t5", "rows": {"보호망": ("㎡", Fraction("1.05"))},
        "labor": Fraction("0.04"), "note_chunk": "p109-x21",
        "note_quote": "※ 위 재료량은 할증이 포함되어 있으며, 보호망의 손율은 1회사용 후 100%로 한다.",
    },
}
audit = {"status": "pass", "sections": {}, "all_rules_fully_verified": False}
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
for section, case in CASES.items():
    spec = json.loads(case["path"].read_text(encoding="utf-8"))["draft"]
    table = next(t for t in spec["tables"] if t["id"] == case["table"])
    for row, (unit, expected) in case["rows"].items():
        value = Fraction(table["values"][row]["수량"])
        assert value == expected, (section, row, value, expected)
        assert unit.replace("kg", "㎏") in table["unit"] or (section == "2-10-2" and row == "방진망")
    note = next(x for x in spec["quantity_model"]["params"]["note_adjustments"]
                if x.get("implemented_by") == "additional_materials_included_allowance")
    assert note["material_table_ids"] == [case["table"]]
    assert note["cite"]["chunk_id"] == case["note_chunk"]
    assert note["cite"]["quote"] == case["note_quote"]
    routes = []
    for area in ("10", "25"):
        result = per_unit(spec, {"quantity": area})
        assert result["status"] == "computed", result
        lines = {(line["kind"], line["name"]): line for line in result["unit_lines"]}
        expected_labor_rate = case["labor"] / 10
        assert Fraction(lines[("labor", "비계공")]["exact"]) == expected_labor_rate
        checked = {}
        for name, (_, coefficient) in case["rows"].items():
            line = lines[("material", name)]
            assert Fraction(line["exact"]) == coefficient
            checked[name] = {"source_coefficient": str(coefficient),
                             "area": area, "expected_total": str(coefficient * Fraction(area))}
        assert len(lines) == len(case["rows"]) + 1
        prices = price_unit(spec, result["unit_lines"], select_rate_version("2026-10-19"),
                            {"quantity": area}, "2026-10-19")
        assert prices["status"] in ("PARTIAL", "OK"), prices
        routes.append({"area_m2": area, "labor_rate_per_m2": str(expected_labor_rate),
                       "labor_total_person_days": str(expected_labor_rate * Fraction(area)),
                       "materials": checked, "offline_price_status": prices["status"]})
    chunks = load_chunks(chunks_path)
    validation = validate_one(case["path"], ROOT / "data/drafts", chunks,
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    audit["sections"][section] = {
        "physical_page": case["page"], "source_table": case["table"],
        "independent_numeric_source_cells": len(case["rows"]),
        "note_rule_checks": 1, "routes": routes, "draft_validation": "pass",
        "visual_original_page": f"evals/runtime_validation/source-p{case['page']}-mesh-materials.png",
        "spec_sha256": hashlib.sha256(case["path"].read_bytes()).hexdigest(),
    }
out = ROOT / "evals/runtime_validation/per-unit-2-10-2-2-8-9-material-rates-audit-2026-10-19.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": audit["status"], "sections": list(audit["sections"]),
                  "independent_cells": sum(x["independent_numeric_source_cells"] for x in audit["sections"].values()),
                  "routes": sum(len(x["routes"]) for x in audit["sections"].values())}, ensure_ascii=False))
