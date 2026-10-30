"""Source-derived checks for pipe-shoring crew and spacing adjustments."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("2-6-2.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    source = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[100].extract_text() or ""
    for text in ("65", "55", "17%", "11%", "0.02", "0.01"):
        assert text in source, text

    heights = next(x for x in spec["inputs"] if x["name"] == "height")["allowed_values"]
    spacings = next(x for x in spec["inputs"] if x["name"] == "spacing")["allowed_values"]
    crew_trades = spec["quantity_model"]["params"]["crew"]["trades"]
    cases = [(heights[0], spacings[0], 65, Fraction(83, 100)),
             (heights[0], spacings[1], 65, Fraction(1)),
             (heights[0], spacings[2], 65, Fraction(111, 100)),
             (heights[1], spacings[1], 55, Fraction(1))]
    for height, spacing, base_output, factor in cases:
        inputs = {"height": height, "spacing": spacing, "quantity": "100",
                  "horizontal_tie_needed": False, "ground_installation": False}
        result = adjusted_daily_crew(spec, inputs, labor_only=True)
        assert result["status"] == "computed", result
        daily = Fraction(base_output) * factor
        days = Fraction(100, 1) / daily
        assert Fraction(result["daily_volume_m3"]) == daily
        assert Fraction(result["work_days"]) == days
        assert sorted(Fraction(v) for v in result["person_days"].values()) == sorted((3 * days, days))
        assert result["provenance"]["daily_volume_m3"]["output_adjustments"]

    tied = adjusted_daily_crew(spec, {"height": heights[0], "spacing": spacings[1], "quantity": "100",
                                      "horizontal_tie_needed": True, "ground_installation": False}, labor_only=True)
    assert tied["status"] == "computed", tied
    assert sorted(Fraction(v) for v in tied["person_days"].values()) == sorted((3 * Fraction(100, 65) + 2,
                                                                                 Fraction(100, 65) + 1))
    blocked = adjusted_daily_crew(spec, {"height": heights[0], "spacing": spacings[1], "quantity": "100",
                                         "horizontal_tie_needed": False, "ground_installation": True}, labor_only=True)
    assert blocked["status"] == "blocked", blocked
    invalid = adjusted_daily_crew(spec, {"height": heights[0], "spacing": spacings[1], "quantity": "100",
                                         "horizontal_tie_needed": "false", "ground_installation": False}, labor_only=True)
    assert invalid["status"] == "rejected", invalid
    print("PASS p.45 rates, signed spacing adjustments including explicit dash cell, tie labor, source citation, and ground-scope/input rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
