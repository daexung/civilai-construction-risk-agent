"""Independently verify signed daily-output adjustments and mower overhead."""
from __future__ import annotations

import json
import sys
import unicodedata
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).replace(",", "").casefold()


def load_spec(division: str, section: str) -> tuple[Path, dict]:
    path = ROOT / "data/drafts/specs" / division / f"{section}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))["draft"]


def main() -> int:
    with pymupdf.open(PDF) as doc:
        p45 = norm(doc[100].get_text())
        for token in ("2-6-1강관동바리설치및해체", "50", "45", "40", "-17%", "+11%"):
            assert norm(token) in p45, token
        p863 = norm(doc[918].get_text())
        for token in ("1-2-11잔디깎기", "3300", "4000", "-30%", "-20%", "8%", "7%"):
            assert norm(token) in p863, token
        assert "그물막이" in doc[918].get_text() and "2인" in doc[918].get_text()

    paths = []
    strut_path, strut = load_spec("공통", "2-6-1")
    paths.append(strut_path)
    strut_expected = {"2.5m이하": Fraction(50),
                      "2.5m초과∼3.5m이하": Fraction(45),
                      "3.5m초과∼4.2m이하": Fraction(40)}
    changes = {"0.6m이하": Fraction(-17, 100),
               "0.6m초과∼0.8m이하": Fraction(0),
               "0.8m초과": Fraction(11, 100)}
    strut_cases = 0
    for height, base in strut_expected.items():
        for spacing, change in changes.items():
            expected = base * (1 + change)
            result = adjusted_daily_crew(strut, {"height": height, "spacing": spacing, "volume": "100"})
            assert result.get("status") == "computed", result
            assert Fraction(result["daily_volume_m3"]) == expected, (height, spacing, result)
            assert Fraction(result["person_days"]["형틀목공"]) == Fraction(300, 1) / expected, result
            assert Fraction(result["person_days"]["보통인부"]) == Fraction(100, 1) / expected, result
            strut_cases += 1

    mower_path, mower = load_spec("유지관리", "1-2-11")
    paths.append(mower_path)
    rate_expected = {"배부식": Fraction(3300), "핸드가이드식": Fraction(4000)}
    frequency_change = {"연1회": Fraction(-30, 100), "연2회": Fraction(-20, 100),
                        "연3회 이상": Fraction(0)}
    mower_cases = 0
    price_cases = 0
    rate_version = select_rate_version("2026-10-01")
    assert rate_version is not None
    for machine, base in rate_expected.items():
        for frequency, change in frequency_change.items():
            expected_output = base * (1 + change)
            for net_required in (False, True):
                inputs = {"machine_type": machine, "annual_frequency": frequency,
                          "net_required": net_required, "area": "100"}
                result = adjusted_daily_crew(mower, inputs)
                assert result.get("status") == "computed", result
                assert Fraction(result["daily_volume_m3"]) == expected_output, (inputs, result)
                work_days = Fraction(100, 1) / expected_output
                special_count = 3 if machine == "배부식" else 1
                assert Fraction(result["person_days"]["특별인부"]) == work_days * special_count, result
                assert Fraction(result["person_days"]["보통인부"]) == work_days * (1 + (2 if net_required else 0)), result
                priced = price_unit(mower, result["unit_lines"], rate_version, inputs, "2026-10-01")
                costs = priced["cost_lines"]
                expected_rate = Decimal("0.08") if machine == "배부식" else Decimal("0.07")
                assert len(costs) == 1 and Decimal(costs[0]["rate"]) == expected_rate, (inputs, costs)
                assert costs[0]["citations"][0]["value"] == ("8%" if machine == "배부식" else "7%"), costs
                assert costs[0]["citations"][0]["column"] == ("배부식 기계" if machine == "배부식" else "핸드가이드식 기계"), costs
                assert Decimal(costs[0]["amount_exact"]) == Decimal(priced["labor_subtotal"]) * expected_rate
                mower_cases += 1
                price_cases += 1

    chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
    validations = [validate_one(path, ROOT / "data/drafts/specs", chunks, None) for path in paths]
    assert all(item["ok"] for item in validations), validations
    report = {
        "status": "pass",
        "root_cause": "source-signed percentage cells were treated as multipliers; '-' source choices were not declared as zero change",
        "source_checks": [
            {"section": "공통/2-6-1", "printed_page": 45, "source_cells": 8,
             "grid": "three height outputs, two crew counts, three installation-spacing rates"},
            {"section": "유지관리/1-2-11", "printed_page": 863, "source_cells": 12,
             "grid": "two machine outputs and four crew counts, three annual-frequency rates, netting note, conditional expense rates 8%/7%"},
        ],
        "source_visual_review": "printed PDF p.45 and p.863 table grids visually compared",
        "calculation_cases": {"strut_height_x_spacing": strut_cases, "mower_machine_x_frequency_x_netting": mower_cases,
                              "mower_conditional_price_rates": price_cases},
        "all_rule_claim": False,
        "remaining_source_note": "strut source [주]⑤ material-cost 5% remains outside the labor-based cost-rule engine and is not claimed calculated",
    }
    out = ROOT / "evals/runtime_validation/signed-daily-output-rates-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
