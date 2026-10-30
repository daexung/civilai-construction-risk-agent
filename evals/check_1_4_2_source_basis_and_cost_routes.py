"""Audit source cells, declared denominator, all four routes and offline costs."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC_PATH = ROOT / "data/drafts/specs/건축/1-4-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
METHODS = {"데크플레이트 자동용접": (2, "0.22"), "데크플레이트 수동용접": (3, "0.18"),
           "지하 철골 기둥 자동용접": (4, "0.22"), "지하 철골 기둥 수동용접": (5, "0.18")}


def main() -> None:
    page = fitz.open(PDF)[631]
    text = page.get_text()
    assert "1-4-2 스터드볼트(Stud bolt) 설치" in text and "1,000개당" in text
    source_table = page.find_tables().tables[1].extract()
    source_rows = source_table[2][0].splitlines()
    assert source_rows == ["용 접 공", "특 별 인 부"]
    original = {}
    for method, (column, _) in METHODS.items():
        source_values = source_table[2][column].splitlines()
        assert len(source_values) == 2
        original[method] = dict(zip(("용접공", "특별인부"), source_values))

    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    declared = {method: {trade: cells[method] for trade, cells in spec["tables"][0]["values"].items()}
                for method in METHODS}
    assert declared == original
    assert spec["tables"][0]["unit"] == "인/1,000개"
    assert spec["quantity_model"]["params"]["note_adjustments"][0]["implemented_by"] == \
        "unit_rate_table source denominator 인/1,000개"

    from pipeline.validate_drafts import chunks_by_id_from_list, validate_one
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()])
    valid = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, None)
    assert valid["ok"], valid

    from backend.agent.tools.calc.per_unit import per_unit
    from backend.agent.tools.calc.price import price_unit, select_rate_version
    cases = []
    for method, (_, expected_rate) in METHODS.items():
        inputs = {"installation_type": method, "quantity": "5000"}
        result = per_unit(spec, inputs, labor_only=True)
        assert result["status"] == "computed", (inputs, result)
        rates = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        expected = {trade: Fraction(value) / 1000 for trade, value in original[method].items()}
        assert rates == expected, (inputs, rates, expected)
        priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-06-01"), inputs)
        assert priced["partial"] is True, priced  # 잡재료는 원문상 주재료비 5%이나 주재료 값 미입력
        cost = next(item for item in priced["cost_lines"] if item["rate"] == expected_rate)
        assert cost["amount_exact"] is not None and cost["reason"] is None
        assert Fraction(cost["amount_exact"]) == Fraction(priced["labor_subtotal"]) * Fraction(expected_rate)
        assert len([item for item in priced["cost_lines"] if item["name"].startswith("공구손료")]) == 1
        cases.append({"installation_type": method, "rates_per_piece": {k: str(v) for k, v in rates.items()},
                      "equipment_rate": expected_rate, "cost_exact": cost["amount_exact"]})

    report = {"status": "all_source_cells_and_declared_routes_verified", "id": spec["id"],
              "source": {"physical_page": 632, "printed_page": 576, "rate_cells": 8,
                         "quantity_basis": "1,000개당", "source_matrix_reconstructed_from_original_pdf": True},
              "runtime": {"method_routes": len(cases), "offline_price_cases": len(cases),
                          "per_unit_routes_verified": True, "full_rules_verified": False,
                          "open": "One-row weld scope and non-top-down installation remain source-scope questions; consumable material 5% waits for an independently supplied principal-material amount."},
              "cases": cases}
    out = ROOT / "evals/runtime_validation/1-4-2-source-basis-calc-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
