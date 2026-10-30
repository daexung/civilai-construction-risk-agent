"""Source-derived checks for PC wall installation."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("6-7-5.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    page = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[212].extract_text() or ""
    for value in ("12", "11", "10", "8", "6", "10%", "17%"):
        assert value in page, value

    weights = next(x for x in spec["inputs"] if x["name"] == "weight_band")["allowed_values"]
    base_rates = [12, 11, 10, 8, 6]
    for weight, base in zip(weights, base_rates):
        for over_height in (False, True):
            result = adjusted_daily_crew(spec, {"weight_band": weight, "quantity": "24",
                                                "height_over_30m": over_height}, labor_only=True)
            assert result["status"] == "computed", result
            output = Fraction(base) * (Fraction(9, 10) if over_height else 1)
            days = Fraction(24) / output
            assert Fraction(result["daily_volume_m3"]) == output
            assert Fraction(result["work_days"]) == days
            assert sorted(Fraction(v) for v in result["person_days"].values()) == sorted((3 * days, 2 * days))
            assert Fraction(next(iter(result["equipment_days"].values()))) == days
            assert result["provenance"]["daily_volume_m3"]["base_output"]["citations"]
            if over_height:
                assert result["provenance"]["daily_volume_m3"]["output_adjustments"][0]["citations"]

    invalid = adjusted_daily_crew(spec, {"weight_band": "outside source scope", "quantity": "24",
                                         "height_over_30m": False}, labor_only=True)
    assert invalid["status"] == "rejected", invalid
    print("PASS p.157 five weight bands × height condition, source crew/crane, 10% output reduction, citations, and invalid scope rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
