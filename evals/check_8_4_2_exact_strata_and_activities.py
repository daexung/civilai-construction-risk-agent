"""Audit original-page sample cells and all conditional activity routes offline."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/토목/8-4-2.json"
OUT = ROOT / "evals/runtime_validation/8-4-2-strata-activity-source-calc-audit-2026-10-19.json"
SAMPLES = [
    ({"rock_type": "풍화암", "diameter": "100", "quantity": "10", "depth": "20", "additional_work": "없음"},
     {"중급기술자": "0.02", "특별인부": "0.03", "고성능착정기": "0.26", "윙비트": "0.044", "벤토나이트": "0.35"}),
    ({"rock_type": "연암", "diameter": "300", "quantity": "5", "depth": "50", "additional_work": "없음"},
     {"중급기술자": "0.02", "특별인부": "0.05", "고성능착정기": "0.38", "기포제": "2.11", "에어해머": "0.0004"}),
    ({"rock_type": "보통암", "diameter": "350", "quantity": "2", "depth": "200", "additional_work": "없음"},
     {"중급기술자": "0.05", "특별인부": "0.11", "고성능착정기": "0.84", "기포제": "8.73", "버튼(Button)비트": "0.0043"}),
    ({"rock_type": "경암", "diameter": "200", "quantity": "3", "depth": "120", "additional_work": "없음"},
     {"중급기술자": "0.04", "특별인부": "0.07", "고성능착정기": "0.58", "기포제": "1.15", "에어해머": "0.0033"}),
]
ACTIVITIES = [
    ("케이싱설치", "additional_work_quantity_casing", "m", "풍화암", "200", "5",
     ["0.03", "0.13", "0.13", "0.13", "0.20"]),
    ("에어써징", "additional_work_quantity_air_surge", "m", "연암", "150", "5",
     ["0.004", "0.01", "0.01", "0.01", "0.02"]),
    ("우물설치", "additional_work_quantity_well", "m", "보통암", "100", "3",
     ["0.004", "0.01", "0.01", "0.01", "0.02"]),
    ("양수시험", "additional_work_quantity_pumping", "시간", "경암", "300", "2",
     ["0.06", "0.12", "0.12", "0.12", "0.37"]),
]
TRADES = ["중급기술자", "중급숙련기술자", "보링공", "특별인부", "보통인부"]


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    tables = {item["id"]: item for item in spec["tables"]}
    source_cells = []
    # Independently transcribed from saved original-page images p459 and p460.
    for inputs, expected in SAMPLES:
        table_id = spec["quantity_model"]["params"]["unit_rate_table"]["table_selector"]["routes"]
        table_id = next(route["table"] for route in table_id
                        if route["when"]["rock_type"] == inputs["rock_type"])
        for trade, rate in expected.items():
            # Source label and original image table are verified for every sample.
            row = tables[table_id]["values"][trade]
            column = next(key for key in row if key.endswith(inputs["diameter"])
                          and key.startswith(inputs["rock_type"]))
            assert Fraction(row[column]) == Fraction(rate), (table_id, trade, column, row[column], rate)
            source_cells.append({"table": table_id, "row": trade, "column": column, "value": rate})
        result = per_unit(spec, inputs, labor_only=True)
        assert result["status"] == "computed", result
        lines = {line["name"]: line["applied"] for line in result["unit_lines"]}
        for trade, rate in expected.items():
            assert Fraction(lines[trade]) == Fraction(rate), (inputs, trade, lines.get(trade), rate)

    activity_cells = []
    for activity, quantity_name, unit, rock, diameter, quantity, expected_rates in ACTIVITIES:
        source_row = tables["p460-t2"]["values"][activity]
        assert source_row["단위"] == unit
        inputs = {"rock_type": rock, "diameter": diameter, "quantity": "1", "depth": "10",
                  "additional_work": activity, quantity_name: quantity}
        result = per_unit(spec, inputs, labor_only=True)
        assert result["status"] == "computed", result
        lines = {line["name"]: line["applied"] for line in result["unit_lines"]}
        for trade, column, expected in zip(TRADES,
                ["인력품 중급\n기술자", "인력품 중급숙련\n기술자", "인력품 보링공",
                 "인력품 특별\n인부", "인력품 보통\n인부"], expected_rates):
            assert Fraction(source_row[column]) == Fraction(expected)
            assert Fraction(lines[trade]) == Fraction(expected), (activity, trade, lines.get(trade), expected)
            activity_cells.append({"table": "p460-t2", "row": activity, "column": column,
                                   "value": expected, "input_unit": unit})

    blocked = per_unit(spec, {"rock_type": "풍화암", "diameter": "100", "quantity": "1",
                              "depth": "201", "additional_work": "없음"}, labor_only=True)
    assert blocked["status"] == "blocked", blocked
    unsupported_diameter = per_unit(spec, {"rock_type": "연암", "diameter": "400", "quantity": "1",
                                           "depth": "10", "additional_work": "없음"}, labor_only=True)
    assert unsupported_diameter["status"] == "unresolvable", unsupported_diameter
    OUT.write_text(json.dumps({
        "status": "original_page_sample_cells_and_all_activity_routes_verified",
        "id": spec["id"],
        "source_images": ["source-p459-8-4-2.png", "source-p460-8-4-2.png"],
        "source": {"primary_sample_cells": len(source_cells), "activity_cells": len(activity_cells),
                   "primary_tables": 4, "all_four_activity_rows_and_five_labor_cells_each": True},
        "runtime": {"calculation_cases": len(SAMPLES) + len(ACTIVITIES),
                    "assertions": sum(map(len, [expected for _, expected in SAMPLES])) + len(activity_cells),
                    "depth_over_200_blocked": True, "unsupported_diameter_rejected": True,
                    "full_rules_verified": False,
                    "unverified": "Not every cell in four primary matrices independently matched to source images; unit-price coverage not completed."},
        "cells": source_cells + activity_cells,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "verified", "source_cells": len(source_cells),
                      "activity_cells": len(activity_cells), "cases": len(SAMPLES) + len(ACTIVITIES),
                      "full_rules_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
