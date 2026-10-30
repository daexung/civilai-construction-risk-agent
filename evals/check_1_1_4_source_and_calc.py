"""Focused source-rule, full selector-matrix, and offline price audit for 1-1-4."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/1-1-4.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "ø25": ("3", "1", "54"), "32": ("3", "1", "45"), "40": ("3", "1", "40"),
    "50": ("3", "1", "30"), "65": ("3", "1", "25"), "80": ("3", "1", "20"),
    "100": ("3", "1", "14"), "125": ("3", "1", "11"), "150": ("3", "1", "9.5"),
    "200": ("4", "1", "8.5"), "250": ("4", "1", "7.0"), "300": ("4", "1", "5.5"),
    "350": ("4", "1", "4.5"), "400": ("4", "1", "3.8"), "450": ("4", "1", "3.5"),
    "500": ("4", "1", "3.0"), "550": ("4", "1", "2.7"), "600": ("4", "1", "2.5"),
}


def main() -> None:
    pdf = fitz.open(PDF)
    page = pdf[702]
    raw = page.get_text()
    assert "1-1-4 그루브조인트식 접합 및 배관" in raw
    assert "26%를 가산한다" in raw and "2%로 계상하고" in raw and "10%로 계상한다" in raw
    tables = page.find_tables().tables
    data = tables[0].extract()
    reconstructed = {}
    for row in data[1:3]:
        trades, counts, sizes, outputs = row[0].splitlines(), row[2].splitlines(), row[3].splitlines(), row[4].splitlines()
        assert len(trades) == len(counts) == 2 and len(sizes) == len(outputs)
        for size, output in zip(sizes, outputs):
            reconstructed[size] = (counts[0], counts[1], output)
    assert reconstructed == EXPECTED, (reconstructed, EXPECTED)
    assert tables[1].extract() == [["시공위치", "화장실배관", "기계실배관", "옥외배관(암거내)"],
                                   ["요 율", "- 17%", "- 23%", "+ 11%"]]

    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    declared = {k: (v["배관공"], v["보통인부"], v["시공량(m)"])
                for k, v in spec["tables"][0]["values"].items()}
    assert declared == EXPECTED
    from pipeline.validate_drafts import chunks_by_id_from_list, validate_one
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()])
    valid = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, None)
    assert valid["ok"], valid

    from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
    location_factors = {"일반": Fraction(1), "화장실배관": Fraction(83, 100),
                        "기계실배관": Fraction(77, 100), "옥외배관(암거내)": Fraction(111, 100)}
    cases = 0
    for size, (plumbers, helpers, base_output) in EXPECTED.items():
        for location, factor in location_factors.items():
            for lift in (False, True):
                output = Fraction(base_output) * factor * (Fraction(126, 100) if lift else 1)
                inputs = {"pipe_size": size, "quantity": str(output * 2), "location": location, "lift_used": lift}
                result = adjusted_daily_crew(spec, inputs, labor_only=True)
                assert result["status"] == "computed", (inputs, result)
                assert Fraction(result["daily_volume_m3"]) == output and Fraction(result["work_days"]) == 2, (inputs, result)
                assert {k: Fraction(v) for k, v in result["person_days"].items()} == {
                    "배관공": 2 * int(plumbers), "보통인부": 2 * int(helpers)}, (inputs, result)
                cases += 1

    from backend.agent.tools.calc.price import price_unit, select_rate_version
    for lift, rate in ((False, "0.02"), (True, "0.10")):
        inputs = {"pipe_size": "ø25", "quantity": "54", "location": "일반", "lift_used": lift}
        result = adjusted_daily_crew(spec, inputs, labor_only=True)
        priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-06-01"), inputs)
        assert priced["status"] == "PARTIAL" and priced["partial"], priced
        cost = next(item for item in priced["cost_lines"] if item["name"] == "공구손료 및 경장비")
        assert cost["rate"] == rate
        assert cost["amount_exact"] is not None and cost["reason"] is None
        assert Fraction(cost["amount_exact"]) == Fraction(priced["labor_subtotal"]) * Fraction(rate)

    report = {"status": "source_rules_matrix_and_offline_price_verified", "id": spec["id"],
              "source": {"physical_page": 703, "printed_page": 647, "base_rows": len(reconstructed),
                         "location_cells": 3, "source_table_matrix_matches_original_pdf": True},
              "runtime": {"cases": cases, "coverage": "18 sizes × 4 locations × 2 lift states",
                          "offline_price_cases": 2, "full_rules_verified": True}}
    out = ROOT / "evals/runtime_validation/1-1-4-source-calc-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
