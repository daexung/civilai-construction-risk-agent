"""Independent source table and arithmetic audit for Tainter Gate guide metal."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-6-13.json").read_text(encoding="utf-8"))["draft"]
SOURCE = {
    "기술관리": {"기계기사": "8.0"}, "재료절단사도": {"제도공": "2.0"},
    "현도": {"현도공": "1.4"}, "괘서": {"마킹공": "2.8"},
    "재료절단": {"절단공": "0.52"}, "단재가공괘서": {"마킹공": "2.8"},
    "절단": {"산소절단공": "0.26", "플랜트기계설치공": "2.3"},
    "Edge": {"산소절단공": "1.1"}, "용접": {"플랜트용접공": "0.78"},
    "교정": {"플랜트제관공": "0.75"}, "Holing": {"플랜트제관공": "0.62"},
    "부분조립취부조정": {"플랜트기계설치공": "6.2"}, "용접 ": {"플랜트용접공": "3.9"},
    "교정 ": {"플랜트제관공": "1.75"}, "기계가공": {"기계설비공": "10"},
    "가조립조립": {"플랜트기계설치공": "2.0"}, "해체": {"플랜트기계설치공": "1.0"},
    "운반조작": {"특수비계공": "5.0"}, "동력조작": {"플랜트전공": "2.0"},
    "보조": {"특별인부": "2.5"},
}
NOTE_ROW, NOTE_COL = "검사", "인력품의 7%"

def main():
    table = next(x for x in SPEC["tables"] if x["id"] == "p873-t1")
    assert {r: c for r, c in table["values"].items() if r != NOTE_ROW} == SOURCE
    assert table["values"][NOTE_ROW] == {NOTE_COL: ""}
    expected_cells = [(row, trade, Fraction(rate)) for row, cells in SOURCE.items()
                      for trade, rate in cells.items()]
    result = per_unit(SPEC, {"quantity": "2"}, labor_only=True)
    assert result["status"] == "computed" and len(result["unit_lines"]) == len(expected_cells) == 21, result
    expected_unit_total = sum((value for _, _, value in expected_cells), Fraction(0)) * Fraction(107, 100)
    actual_unit_total = Fraction(0)
    assert len(result["provenance"]["input_rate_adjustments"]) == 1
    trace = result["provenance"]["input_rate_adjustments"][0]
    assert trace["rate"] == "7" and trace["operation"] == "add_source_percent"
    assert len(trace["resources"]) == 21
    for line in result["unit_lines"]:
        source = line["citations"][0]
        key = (source["row"], source["column"])
        expected = next(value for row, trade, value in expected_cells if (row, trade) == key)
        assert source["internal_id"] == "p873-t1" and Fraction(source["value"]) == expected
        assert Fraction(line["exact"]) == expected * Fraction(107, 100)
        assert line["unit"] == "인/ton"
        assert any(c.get("row") == NOTE_ROW and c.get("column") == NOTE_COL
                   and c.get("internal_id") == "p873-t1" for c in line["citations"])
        actual_unit_total += Fraction(line["exact"])
    assert actual_unit_total == expected_unit_total
    price = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"),
                       {"quantity": "2"}, "2026-10-19")
    assert price["status"] in ("PRICED", "PARTIAL") and len(price["lines"]) == 21
    report = {
        "status": "passed", "source_pdf_page": 873, "printed_page": 817,
        "numeric_source_cells_independently_compared": len(expected_cells),
        "source_percent_rule_cells_independently_compared": 1,
        "source_process_rows": len(SOURCE), "runtime_output_lines": len(result["unit_lines"]),
        "independent_per_ton_sum_after_7_percent": str(expected_unit_total),
        "quantity_2_total_person_days": str(expected_unit_total * 2),
        "offline_price_status": price["status"], "full_rule_verification": False,
    }
    (ROOT / "evals/runtime_validation/13-6-13-source-rates-and-7-percent-audit-2026-10-19.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
