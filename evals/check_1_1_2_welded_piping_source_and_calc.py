"""Focused original-source, rule, calculation, and offline price audit for 1-1-2."""
import json
import sys
from pathlib import Path
from fractions import Fraction

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/1-1-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "ø15": ("3", "1", "83"), "20": ("3", "1", "75"), "25": ("3", "1", "60"),
    "32": ("3", "1", "50"), "40": ("3", "1", "45"), "50": ("3", "1", "37"),
    "65": ("3", "1", "30"), "80": ("3", "1", "25"), "100": ("3", "1", "18"),
    "125": ("3", "1", "14"), "150": ("3", "1", "12"), "200": ("4", "1", "10"),
    "250": ("4", "1", "8.0"), "300": ("4", "1", "6.0"), "350": ("4", "1", "5.0"),
    "400": ("4", "1", "4.0"),
}


def main() -> None:
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "adjusted_daily_crew"
    assert spec["quantity_model"]["name"] == "adjusted_daily_crew"

    pdf = fitz.open(PDF)
    page = pdf[700]
    tables = page.find_tables().tables
    source = tables[1].extract()
    assert source[0] == ["구 분", "단 위", "수 량", "관규격(㎜)", "시공량(m)"]
    source_map = {}
    for row in source[1:]:
        trade, unit, count, sizes, outputs = row
        trades, units, counts = trade.splitlines(), unit.splitlines(), count.splitlines()
        sizes, outputs = sizes.splitlines(), outputs.splitlines()
        assert len(trades) == len(units) == len(counts) == 2
        assert len(sizes) == len(outputs)
        crew = dict(zip(trades, counts))
        for size, output in zip(sizes, outputs):
            source_map[size] = (crew["배 관 공"], crew["보 통 인 부"], output)
    expected_source = {k: (v[0], v[1], v[2]) for k, v in EXPECTED.items()}
    assert source_map == expected_source, (source_map, expected_source)
    assert {k: (v["배관공"], v["보통인부"], v["시공량(m)"])
            for k, v in next(t for t in spec["tables"] if t["id"] == "p701-t1")["values"].items()} == expected_source

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
        for location, location_factor in location_factors.items():
            for use_lift in (False, True):
                output = Fraction(base_output) * location_factor * (Fraction(126, 100) if use_lift else 1)
                inputs = {"location": location, "use_lift": use_lift, "pipe_size": size,
                          "quantity": str(output * 2)}
                result = adjusted_daily_crew(spec, inputs, labor_only=True)
                assert result["status"] == "computed", (inputs, result)
                assert Fraction(result["daily_volume_m3"]) == output, (inputs, output, result)
                assert Fraction(result["work_days"]) == 2, (inputs, result)
                assert {k: Fraction(v) for k, v in result["person_days"].items()} == {
                    "배관공": Fraction(plumbers) * 2, "보통인부": Fraction(helpers) * 2}, (inputs, result)
                cases += 1

    from backend.agent.tools.calc.price import price_unit
    from backend.agent.tools.calc.price import select_rate_version
    version = select_rate_version("2026-06-01")
    for use_lift, expected_rate in ((False, "0.02"), (True, "0.10")):
        inputs = {"location": "일반", "use_lift": use_lift, "pipe_size": "25", "quantity": "60"}
        lines = adjusted_daily_crew(spec, inputs, labor_only=True)["unit_lines"]
        priced = price_unit(spec, lines, version, inputs)
        cost = [row for row in priced["cost_lines"] if row["name"] == "공구손료 및 경장비"]
        assert len(cost) == 1 and cost[0]["rate"] == expected_rate, (priced, cost)
        expected_exact = Fraction(priced["labor_subtotal"]) * Fraction(expected_rate)
        assert Fraction(cost[0]["amount_exact"]) == expected_exact, (expected_exact, cost)

    report = {
        "status": "source_rules_calculation_and_offline_price_verified",
        "id": spec["id"], "source": {"physical_page": 701, "printed_page": 645, "base_cells": len(source_map),
                    "independently_reconstructed_from_original_pdf": True},
        "rules": {"location_rates_from_printed_page_646": ["-17%", "-23%", "+11%"],
                  "lift_output_increase": "26%", "equipment_cost_rates": {"without_lift": "2%", "with_lift": "10%"}},
        "runtime": {"cases": cases, "offline_price_cases": 2, "calculation_matrix_coverage": "16 diameters × 4 locations × 2 lift states",
                    "full_rules_verified": False},
    }
    out = ROOT / "evals/runtime_validation/1-1-2-welded-piping-source-calc-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
