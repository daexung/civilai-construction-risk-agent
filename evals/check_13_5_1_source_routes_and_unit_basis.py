"""Independent printed-cell, selector, unit, 10% and offline pricing audit."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-5-1.json").read_text(encoding="utf-8"))["draft"]
SOURCE = {
    "기술관리": ("p826-t0", "기술관리 Boiler 본체 설비공사 기간중", "일", {"기계기사": "2.0"}),
    "포장해체": ("p826-t0", "포장해체 수송을 위해 포장된 목재를 해체하고 목재를 소정 위치에 정리함", "㎥", {"목공": "0.02", "특별인부": "0.02"}),
    "표면손질": ("p826-t0", "표면손질", "㎡", {"특별인부": "0.1"}),
    "용접면손질": ("p826-t0", "용접면손질 용착 효율을 높이기 위하여 용접전에 Grinder 혹은 sand paper로 깨끗이 손질하는 작업 joint당 면적은 2×3.63t(D-t)", "㎡", {"특별인부": "0.39"}),
    "소운반": ("p826-t0", "소운반 Boiler tube용 자재 기타 작업에 필요한 자재를 조양위치까지 운반", "ton", {"비계공": "0.445", "건설기계운전조": "0.124"}),
    "Scaffolder 조립설치 및 철거": ("p826-t0", "Scaffolder 조립설치 및 철거 용접, 검사, 위치조정 등에 필요한 Scaffolder 조립설치(1.5×2.0×1.6m Unit 기준)", "㎡", {"일반기계운전사": "0.0083", "(윈치운전)": "0.0083", "비계공": "0.0083", "특별인부": "0.0083"}),
    "Chain block 설치 및 철거": ("p826-t0", "Chain block 설치 및 철거 Tube Panel 조립시는 6개 설치 기준 Header, Buck stay 조립시는 4개설치 기준", "개", {"용접공": "0.021", "비계공": "0.028", "일반기계운전사": "0.028", "(윈치운전)": "0.028"}),
    "윈치설치 및 철거": ("p826-t0", "윈치설치 및 철거 조양을 위한 윈치 플리 로프 등의 설치와 사용후 철거까지 포함됨.", "대", {"기계설비공": "3.3", "비계공": "11.0", "용접공": "3.3", "특별인부": "4.95", "건설기계운전조": "4.3"}),
    "조양": ("p826-t0", "조양 tube 및 header류, 기타 자재 등을 설치 위치까지 조양해서 가고정하는 작업", "ton", {"플랜트기계설치공": "0.63", "비계공": "0.84", "플랜트용접공": "0.42", "건설기계운전조": "0.56"}),
    "Tube Panel 조립조정": ("p827-t0", "Tube Panel 조립조정 조양된 Panel을 alignment하고 hangering 혹은 supporting 후 가고정 해체함", "개", {"플랜트기계설치공": "2.0", "특별인부": "2.0", "플랜트용접공": "2.0"}),
    "Header류 조립조정": ("p827-t0", "Header류 조립조정 header 및 그에 준하는 것으로서 조양 된 것을 alignment하고 hangering 혹은 supporting후 가고정 해체함", "개", {"플랜트기계설치공": "1.5", "특별인부": "1.5", "플랜트용접공": "1.5"}),
    "Buckstay 조립조정": ("p827-t0", "Buckstay 조립조정 조양된 buckstay를 alignment하고 tiebar 취급함.", "개", {"플랜트기계설치공": "1.5", "특별인부": "1.5", "플랜트용접공": "1.5"}),
    "Tube piece 조립조정": ("p827-t0", "Tube piece 조립조정 낱개로 되어 있는 tube 및 7개 미만의 tube set로 된 것으로서 alignment hangering 부착물 취부함.", "개", {"플랜트기계설치공": "0.4", "특별인부": "0.4", "플랜트용접공": "0.2"}),
    "Casing 조립": ("p827-t0", "Casing 조립 조작으로 분리된 casing의 소재를 성형 용접함", "ton", {"플랜제관공": "0.82", "플랜트용접공": "0.22", "특별인부": "0.92", "건설기계운전조": "0.61"}),
    "Casing 설치": ("p827-t0", "Casing 설치 성형된 casing을 운반, 조양 alignment 후 설치", "ton", {"윈치운전조": "1.01", "비계공": "2.87", "특별인부": "1.33"}),
}
HIGH = {
    "Tube Panel 조립조정": ("Tube Panel 조립조정 조양된 Panel을 alignment하고 hangering 혹은 supporting 후 가고정 해체함", {"플랜트기계설치공": "1.38", "특별인부": "1.45", "플랜트용접공": "1.16"}),
    "Header류 조립조정": ("Header류 조립조정 header 및 그에 준하는 것으로서 조양된 것을 alignment하고 hangering 혹은 supporting후 가고정 해체함", {"플랜트기계설치공": "0.90", "특별인부": "1.02", "플랜트용접공": "0.78"}),
}
RESOURCE_UNITS = {
    ("소운반", "건설기계운전조"): "인",
    ("윈치설치 및 철거", "건설기계운전조"): "조",
    ("조양", "건설기계운전조"): "조",
    ("Casing 조립", "건설기계운전조"): "조",
    ("Casing 설치", "윈치운전조"): "조",
}
NOTE_ROW = "검사 및 교정 외관검사, 수압시험후 casing leak test 교정 작업(비파괴 시험은 제외)"
NOTE_COL = "기술관리, 포장해체를 제외한 모든 품의 10%"

def run(task, capacity=False):
    return per_unit(SPEC, {"work_type": task, "boiler_capacity_500mw_over": capacity, "quantity": "2"}, labor_only=True)

def audit_cells(tables):
    count = 0
    for task, (table, row, _unit, rates) in SOURCE.items():
        assert tables[table]["values"].get(row) == rates, (task, table, row, tables[table]["values"].get(row), rates)
        count += len(rates)
    for task, (row, rates) in HIGH.items():
        assert tables["p827-t1"]["values"].get(row) == rates, (task, row)
        count += len(rates)
    assert tables["p827-t0"]["values"][NOTE_ROW] == {NOTE_COL: ""}
    return count

def check_task(task, capacity=False):
    table, row, denominator, rates = SOURCE[task]
    expected_table, expected_row, expected_rates = table, row, rates
    if capacity and task in HIGH:
        expected_table, (expected_row, expected_rates) = "p827-t1", HIGH[task]
    result = run(task, capacity)
    assert result["status"] == "computed", (task, capacity, result)
    expected_factor = Fraction(1) if task in ("기술관리", "포장해체") else Fraction(11, 10)
    assert len(result["unit_lines"]) == len(expected_rates)
    for line in result["unit_lines"]:
        name = line["name"]
        assert name in expected_rates, (task, line)
        expected_rate = Fraction(expected_rates[name]) * expected_factor
        assert Fraction(line["exact"]) == expected_rate, (task, line, expected_rate)
        assert line["unit"] == f"{RESOURCE_UNITS.get((task, name), '인')}/{denominator}", (task, line)
        source = line["citations"][0]
        assert (source["internal_id"], source["row"], source["column"], source["value"]) == (
            expected_table, expected_row, name, expected_rates[name]), (task, source)
        if expected_factor != 1:
            assert any(c.get("internal_id") == "p827-t0" and c.get("row") == NOTE_ROW
                       and c.get("column") == NOTE_COL for c in line["citations"]), line
    price = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"),
                       {"work_type": task, "boiler_capacity_500mw_over": capacity, "quantity": "2"},
                       "2026-10-19")
    assert price["status"] in ("PRICED", "PARTIAL"), (task, price)
    assert len(price["lines"]) == len(expected_rates)
    return len(expected_rates)

def main():
    tables = {x["id"]: x for x in SPEC["tables"]}
    source_cells = audit_cells(tables)
    tested_lines = sum(check_task(task) for task in SOURCE)
    high_lines = sum(check_task(task, True) for task in HIGH)
    blocked = run("Buckstay 조립조정", True)
    assert blocked["status"] == "blocked" and "Buckstay" in blocked["reason"]
    assert run("기술관리", True)["status"] == "computed"
    report = {
        "status": "passed", "source_pdf_pages": [826, 827], "printed_pages": [770, 771],
        "numeric_source_cells_independently_compared": source_cells,
        "source_rule_cells_independently_compared": 1,
        "work_type_routes": len(SOURCE), "normal_capacity_output_lines": tested_lines,
        "high_capacity_reference_output_lines": high_lines,
        "task_dependent_units": sorted({v[2] for v in SOURCE.values()}),
        "chain_block_source_rates": SOURCE["Chain block 설치 및 철거"][3],
        "source_10_percent": "applied to each eligible work rate; excludes technical management and packing demolition",
        "high_capacity_buckstay": "blocked only for the exact high-capacity Buckstay task; other high-capacity tasks remain calculable",
        "offline_price": "all 15 task routes and both high-capacity reference routes returned PRICED or PARTIAL without external calls",
        "full_rule_verification": False,
    }
    output = ROOT / "evals/runtime_validation/13-5-1-exact-source-routes-audit-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
