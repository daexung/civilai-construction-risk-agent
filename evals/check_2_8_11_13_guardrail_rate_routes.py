"""Independently verify both guardrail source matrices, rate routes and costs."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPACING = {"1.0m이하": (Fraction(11, 10), "110%"), "1.5m이하": (Fraction(1), "100%"),
           "1.5m초과": (Fraction(9, 10), "90%")}
SPECS = {
    "2-8-11": {"page": 110, "main_table": 1, "spacing_table": 2, "id": "2026-정오표1차/공통/2-8-11/안전난간대설치및해체",
                "rates": {"브라켓형 2단": "0.56", "브라켓형 3단": "0.62", "앵커형 2단": "0.64", "앵커형 3단": "0.70"},
                "axis": "type_and_tier", "quantity": "quantity"},
    "2-8-13": {"page": 111, "main_table": 0, "spacing_table": 1, "id": "2026-정오표1차/공통/2-8-13/안전난간대설치및해체",
                "rates": {"2단": "0.62", "3단": "0.67"}, "axis": "tier", "quantity": "length"},
}


def main() -> None:
    pdf = fitz.open(PDF)
    from pipeline.validate_drafts import chunks_by_id_from_list, validate_one
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = chunks_by_id_from_list([json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()])
    from backend.agent.tools.calc.per_unit import per_unit
    from backend.agent.tools.calc.price import price_unit, select_rate_version
    audits = []
    total_cases = 0
    for section, meta in SPECS.items():
        package = json.loads((ROOT / f"data/drafts/specs/공통/{section}.json").read_text(encoding="utf-8"))
        spec = package["draft"]
        assert spec["id"] == meta["id"]
        page = pdf[meta["page"] - 1]
        tables = page.find_tables().tables
        main = tables[meta["main_table"]].extract()
        spacing = tables[meta["spacing_table"]].extract()
        assert spacing == [["난간기둥 간격", "1.0m이하", "1.5m이하", "1.5m초과"],
                           ["요 율", "110%", "100%", "90%"]]
        source_rates = meta["rates"]
        if section == "2-8-11":
            assert main[2][0] == "비 계 공"
            assert dict(zip(("브라켓형 2단", "브라켓형 3단", "앵커형 2단", "앵커형 3단"), main[2][2:])) == source_rates
        else:
            assert main[1][0] == "비 계 공"
            assert dict(zip(("2단", "3단"), main[1][2:])) == source_rates
        declared = spec["tables"][0]["values"]["비계공"]
        assert declared == source_rates
        valid = validate_one(ROOT / f"data/drafts/specs/공통/{section}.json", ROOT / "data/drafts", chunks, None)
        assert valid["ok"], valid

        cases = 0
        for setup, base_raw in source_rates.items():
            for spacing_name, (factor, source_rate) in SPACING.items():
                inputs = {meta["axis"]: setup, "post_spacing": spacing_name, meta["quantity"]: "100"}
                result = per_unit(spec, inputs, labor_only=True)
                assert result["status"] == "computed", (section, inputs, result)
                expected_rate = Fraction(base_raw) * factor / 10
                assert Fraction(result["unit_lines"][0]["exact"]) == expected_rate, (section, inputs, result)
                priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-06-01"), inputs)
                assert priced["partial"] is True, priced
                cost = next(item for item in priced["cost_lines"] if item["name"] == "공구손료 및 경장비")
                assert cost["rate"] == "0.02" and cost["amount_exact"] is not None and cost["reason"] is None
                assert Fraction(cost["amount_exact"]) == Fraction(priced["labor_subtotal"]) / 50
                cases += 1
        total_cases += cases
        audits.append({"section": section, "physical_page": meta["page"], "printed_page": meta["page"] - 56,
                       "table_rate_cells": len(source_rates) + len(SPACING), "calculation_cases": cases,
                       "offline_cost_cases": cases, "full_rules_verified": False,
                       "outside_scope": "toe board and protective net are separately accounted per source"})

    report = {"status": "both_source_rate_matrices_and_calculations_verified", "source": audits,
              "total_calculation_cases": total_cases, "shared_runtime_changes": [],
              "full_rules_verified": False}
    out = ROOT / "evals/runtime_validation/2-8-11-13-guardrail-rate-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
