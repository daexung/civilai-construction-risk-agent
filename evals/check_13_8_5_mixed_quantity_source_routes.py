"""Source-cell, mixed-basis, 10% and offline price audit for 13-8-5."""
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-8-5.json").read_text(encoding="utf-8"))["draft"]
INPUTS = {
    "tech_management_days": "2", "unpacking_vol": "10", "surface_prep_area": "20",
    "transport_weight": "3", "foundation_weight": "4", "calibration_weight": "5",
    "body_assembly_weight": "6", "inner_plate_weight": "7", "weld_prep_weight": "8",
    "body_install_weight": "9", "sealing_weld_weight": "10",
}
ROWS = [
    ("p895-t2", "◦ 기술관리 - 설치공사 기간중", "tech_management_days", "일", "인", {"기계기사": "0.96"}),
    ("p895-t2", "◦ 포장해체 - 수송을 위해 포장된 목재를 해체하고 목재를 정리함", "unpacking_vol", "㎥", "인", {"목공": "0.06", "특별인부": "0.14"}),
    ("p895-t2", "◦ 표면손질", "surface_prep_area", "㎡", "인", {"특별인부": "0.24"}),
    ("p895-t2", "◦ 소운반", "transport_weight", "ton", "인", {"특별인부": "0.66"}),
    ("p895-t2", "- 작업위치까지 필요한 자재를 운반", "transport_weight", "ton", "조", {"건설기계운전조": "0.21"}),
    ("p895-t2", "◦ 기초작업 - Chipping 및 Grouting", "foundation_weight", "ton", "인", {"플랜트기계설치공": "0.01", "특별인부": "0.01"}),
    ("p896-t0", "◦ 현장교정 - 수송도중 변형된 것을 바로 잡기", "calibration_weight", "ton", "인", {"특별인부": "2.07", "플랜트기계설치공": "0.04"}),
    ("p896-t0", "◦ 본체조립 - 분리 운반된 Body 조립 포함", "body_assembly_weight", "ton", "인", {"플랜트제관공": "1.91", "플랜트용접공": "2.04", "특별인부": "3.93"}),
    ("p896-t0", "◦ 본체조립 - 분리 운반된 Body 조립 포함", "body_assembly_weight", "ton", "조", {"건설기계운전조": "1.32"}),
    ("p896-t0", "◦ Inner Plate 및 Hanger 조립 - Suspention Device 조립 포함", "inner_plate_weight", "ton", "인", {"플랜트제관공": "1.14", "플랜트용접공": "3.36", "특별인부": "3.37"}),
    ("p896-t0", "◦ 용접손질 - 용접 Joint부위 용접효율을 높이기 위함", "weld_prep_weight", "ton", "인", {"플랜트제관공": "2.19", "특별인부": "0.07"}),
    ("p896-t0", "◦ 본체 설치 - Reactor 설치 포함", "body_install_weight", "ton", "인", {"플랜트기계설치공": "4.28", "플랜트제관공": "0.54", "비계공": "1.66", "특별인부": "2.28", "플랜트용접공": "3.97"}),
    ("p896-t0", "◦ 본체 설치 - Reactor 설치 포함", "body_install_weight", "ton", "조", {"건설기계운전조": "4.07"}),
    ("p896-t0", "◦ Sealing 용접 - 용접용 Support설치 및 운반포함", "sealing_weld_weight", "ton", "인", {"플랜트용접공": "14.74", "플랜트제관공": "4.99", "특별인부": "1.07"}),
]


def main():
    tables = {table["id"]: table for table in SPEC["tables"]}
    source_cells = 0
    expected_lines = []
    expected_person_days = Fraction(0)
    expected_crew_units = Fraction(0)
    grouped_source_rates = {}
    for table_id, row, _quantity, _unit, _resource_unit, rates in ROWS:
        grouped_source_rates.setdefault((table_id, row), {}).update(rates)
    for table_id, row, quantity, unit, resource_unit, rates in ROWS:
        assert tables[table_id]["values"].get(row) == grouped_source_rates[(table_id, row)], (table_id, row)
        q = Fraction(INPUTS[quantity])
        exempt = quantity in ("tech_management_days", "unpacking_vol")
        for trade, raw in rates.items():
            source_cells += 1
            applied = Fraction(raw) * (Fraction(1) if exempt else Fraction(11, 10))
            expected_lines.append((trade, quantity, f"{resource_unit}/{unit}", applied, table_id, row, raw))
            if resource_unit == "조":
                expected_crew_units += applied * q
            else:
                expected_person_days += applied * q

    percent_row = "◦ 검사 및 교정 - Gas Leak Test 포함"
    percent_column = "기술관리, 포장해체를 제외한 전공량의 10%"
    assert tables["p896-t0"]["values"][percent_row] == {percent_column: ""}
    source_cells += 1
    result = per_unit(SPEC, INPUTS, labor_only=True)
    assert result.get("status") == "computed", result
    assert len(result["unit_lines"]) == len(expected_lines) == 28
    for line, (trade, quantity, unit, expected_rate, table_id, row, raw) in zip(result["unit_lines"], expected_lines):
        assert (line["name"], line.get("quantity_input"), line["unit"]) == (trade, None if quantity == "tech_management_days" else quantity, unit), line
        assert Fraction(line["exact"]) == expected_rate, line
        source = line["citations"][0]
        assert (source["internal_id"], source["row"], source["column"], source["value"]) == (
            table_id, row, trade, raw), source

    trace = result["provenance"]["input_rate_adjustments"][0]
    assert trace["rate"] == "10" and len(trace["resources"]) == 25
    assert all(item["name"] != "기계기사" for item in trace["resources"])
    trace_cite = trace["citations"][0]
    assert trace_cite["internal_id"] == "p896-t0"
    assert (trace_cite["row"], trace_cite["column"]) == (percent_row, percent_column)
    assert expected_person_days > 0 and expected_crew_units > 0

    priced = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"), INPUTS, "2026-10-19")
    assert priced["status"] == "PARTIAL" and len(priced["lines"]) == 28
    missing = Counter(line["name"] for line in priced["lines"] if line["amount"] is None)
    assert missing == Counter({"기계기사": 1, "목공": 1, "건설기계운전조": 3}), missing
    assert len(priced["lines"]) == len(result["unit_lines"])
    not_calculated = result["not_calculated"]
    assert len(not_calculated) == 4
    assert any(item["item"] == "건설기계운전조 편성의 현장조건 조정" for item in not_calculated)
    assert any(item["item"] == "기본 사용장비 경비 및 선택" for item in not_calculated)

    report = {
        "status": "passed", "source_pdf_pages": [895, 896], "printed_pages": [839, 840],
        "numeric_source_cells": source_cells - 1, "source_percent_rule_cells": 1,
        "exact_quantity_row_routes": len(ROWS), "priced_unit_lines": len(result["unit_lines"]),
        "person_days_expected": str(expected_person_days), "crew_quantity_expected": str(expected_crew_units),
        "source_percent": "10% excluding technical management and packing demolition",
        "offline_price_status": priced["status"], "unpriced_wage_lines": dict(missing),
        "not_calculated_notes": [item["item"] for item in not_calculated],
    }
    output = ROOT / "evals/runtime_validation/13-8-5-mixed-quantity-source-calc-audit-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
