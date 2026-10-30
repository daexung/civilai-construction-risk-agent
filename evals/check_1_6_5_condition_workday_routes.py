from __future__ import annotations

import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/토목/1-6-5.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
TABLE = next(t for t in SPEC["tables"] if t["id"] == "p373-t0")
source = {
    "외부 반출/ 반입": {
        "기계설비공": ("1", "3", "2"), "철공": ("3", "3", "2"),
        "특별인부": ("2", "3", "2"), "크레인": ("1", None, None),
    },
    "작업구간 이동": {
        "기계설비공": ("1", "2", "1"), "철공": ("2", "2", "1"),
        "특별인부": ("2", "2", "1"), "크레인": ("1", None, None),
    },
}
routes = []
checked_cells = set()
for condition, trades in source.items():
    input_condition = condition.replace("/ ", "/")
    for work_type, day_index in (("조립", 1), ("해체", 2)):
        result = per_unit(SPEC, {"condition": input_condition, "work_type": work_type, "count": "1"})
        assert result["status"] == "computed", result
        lines = {line["name"]: line for line in result["unit_lines"]}
        expected_total = Fraction(0)
        for trade, (count, assembly_days, dismantle_days) in trades.items():
            source_row = f"{condition} | {trade}"
            row = TABLE["values"][source_row]
            assert row["수량"] == count
            count_line = lines[trade]
            assert any(c.get("internal_id") == "p373-t0" and c.get("row") == source_row
                       and c.get("column") == "수량" and c.get("value") == count
                       for c in count_line["citations"])
            checked_cells.add((source_row, "수량"))
            if assembly_days is not None:
                column = "소요일수(일) 조립" if day_index == 1 else "소요일수(일) 해체"
                days = assembly_days if day_index == 1 else dismantle_days
                assert row[column] == days
                assert Fraction(count_line["exact"]) == Fraction(count) * Fraction(days)
                assert count_line["unit"] == "인·일/회"
                assert any(c.get("internal_id") == "p373-t0" and c.get("row") == source_row
                           and c.get("column") == column and c.get("value") == days
                           for c in count_line["citations"])
                checked_cells.add((source_row, column))
                expected_total += Fraction(count) * Fraction(days)
            else:
                assert count_line["kind"] == "equipment" and count_line["unit"] == "대/회"
                assert Fraction(count_line["exact"]) == 1
        inputs = {"condition": input_condition, "work_type": work_type, "count": "2"}
        repeated = per_unit(SPEC, inputs)
        priced = price_unit(SPEC, repeated["unit_lines"], select_rate_version("2026-10-19"),
                            inputs, "2026-10-19")
        assert priced["status"] == "PARTIAL" and priced["labor_subtotal"] is not None
        cost = next(item for item in priced["cost_lines"] if item["name"] == "공구손료 및 경장비")
        expected_cost = Decimal(priced["labor_subtotal"]) * Decimal("0.03")
        assert Decimal(cost["amount_exact"]) == expected_cost
        assert any(c.get("internal_id") == "p373-x9" for c in cost["citations"])
        routes.append({"condition": input_condition, "work_type": work_type,
                       "labor_person_days_per_event": str(expected_total),
                       "crane_units_per_event": "1", "two_event_offline_price": priced["status"],
                       "equipment_cost_exact": str(expected_cost)})

chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
assert validation["ok"], validation
audit = {
    "id": SPEC["id"], "status": "pass", "physical_page": 373, "printed_page": 317,
    "independent_source_cells": len(checked_cells), "source_rule_checks": 1,
    "routes": routes, "draft_validation": "pass", "all_rules_fully_verified": False,
    "visual_original_page": "evals/runtime_validation/source-p373-equipment-assembly-dismantling.png",
    "separately_tracked": ["Crane capacity and its rental/operating price depend on site conditions and remain unpriced."],
}
out = ROOT / "evals/runtime_validation/per-unit-1-6-5-condition-workday-audit-2026-10-19.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "pass", "independent_source_cells": len(checked_cells),
                  "routes": len(routes), "all_rules_fully_verified": False}, ensure_ascii=False))
