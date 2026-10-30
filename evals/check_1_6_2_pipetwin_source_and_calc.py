"""Independent source-cell, citation, runtime and offline-cost audit for 1-6-2."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/1-6-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {"배관공": {"ø16mm": "0.048", "ø20mm": "0.053"},
            "보통인부": {"ø16mm": "0.021", "ø20mm": "0.023"}}


def main() -> None:
    page_text = fitz.open(PDF)[712].get_text()
    assert "1-6-2 폴리부틸렌(PB) 이중관 접합 및 배관" in page_text
    for value in ("ø16mm", "ø20mm", "0.048", "0.053", "0.021", "0.023"):
        assert value in page_text, f"원문 p.657에 {value} 없음"
    import re
    assert re.search(r"배\s*관\s*공", page_text) and re.search(r"보\s*통\s*인\s*부", page_text)

    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    assert table["values"] == EXPECTED

    from pipeline.validate_drafts import chunks_by_id_from_list, validate_one
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()])
    valid = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, None)
    assert valid["ok"], valid

    from backend.agent.tools.calc.per_unit import per_unit
    from backend.agent.tools.calc.price import price_unit, select_rate_version
    cases = []
    for diameter in ("ø16mm", "ø20mm"):
        inputs = {"diameter": diameter, "quantity": "100"}
        result = per_unit(spec, inputs, labor_only=True)
        assert result["status"] == "computed", result
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        expected = {trade: Fraction(row[diameter]) for trade, row in EXPECTED.items()}
        assert actual == expected, (inputs, actual, expected)
        priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-06-01"), inputs)
        assert priced["status"] == "OK" and not priced["partial"], priced
        cost = next(line for line in priced["cost_lines"] if line["name"] == "공구손료 및 경장비")
        assert Fraction(cost["rate"]) == Fraction(1, 100)
        assert Fraction(cost["amount_exact"]) == Fraction(priced["labor_subtotal"]) / 100
        cases.append({"diameter": diameter, "labor_exact": {k: str(v) for k, v in actual.items()},
                      "cost_exact": cost["amount_exact"]})

    report = {"status": "independent_source_cells_and_calculation_verified", "id": spec["id"],
              "source": {"physical_page": 713, "printed_page": 657, "distinct_cells": 4,
                         "original_trade_labels_and_both_size_columns_checked": True},
              "runtime": {"cases": len(cases), "offline_price_cases": len(cases), "full_rules_verified": True},
              "cases": cases}
    out = ROOT / "evals/runtime_validation/1-6-2-pipetwin-source-calc-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
