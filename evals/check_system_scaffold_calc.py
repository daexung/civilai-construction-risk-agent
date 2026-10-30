"""Source-derived checks for system scaffold installation and dismantling."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("2-7-3.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    table = spec["tables"][0]["values"]
    pdf = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
    source_text = PdfReader(pdf).pages[103].extract_text() or ""
    for expected in ("180", "150", "130", "190", "160", "140", "0.5", "8%"):
        assert expected in source_text, expected

    install = next(x for x in spec["inputs"] if x["name"] == "work_type")["allowed_values"][0]
    dismantle = next(x for x in spec["inputs"] if x["name"] == "work_type")["allowed_values"][1]
    heights = next(x for x in spec["inputs"] if x["name"] == "height")["allowed_values"][:3]
    expected = {
        install: [(180, (4, 1)), (150, (4, 1)), (130, (4, 1))],
        dismantle: [(190, (2, 2)), (160, (2, 2)), (140, (2, 2))],
    }
    for work_type in (install, dismantle):
        for height, (daily_output, crew_counts) in zip(heights, expected[work_type]):
            inputs = {"work_type": work_type, "height": height, "quantity": "100",
                      "safety_net_installed": True}
            result = adjusted_daily_crew(spec, inputs, labor_only=True)
            assert result["status"] == "computed", result
            days = Fraction(100, daily_output)
            assert Fraction(result["work_days"]) == days
            assert sorted(Fraction(x) for x in result["person_days"].values()) == sorted(
                days * count for count in crew_counts)
            assert Fraction(next(iter(result["equipment_days"].values()))) == days / 2
            assert result["daily_volume_m3"] == str(daily_output)
            open_mesh = adjusted_daily_crew(
                spec, {**inputs, "safety_net_installed": False}, labor_only=True)
            assert open_mesh["status"] == "computed"
            assert Fraction(open_mesh["daily_volume_m3"]) == Fraction(daily_output) * Fraction("1.08")
            assert open_mesh["provenance"]["daily_volume_m3"]["output_adjustments"]

    blocked = adjusted_daily_crew(spec, {"work_type": install, "height": "30m초과", "quantity": "100",
                                          "safety_net_installed": True}, labor_only=True)
    assert blocked["status"] == "blocked", blocked
    invalid = adjusted_daily_crew(spec, {"work_type": install, "height": heights[0], "quantity": "100",
                                          "safety_net_installed": "false"}, labor_only=True)
    assert invalid["status"] == "rejected", invalid
    print("PASS system scaffold source rates/crews/equipment, 8% output increase, source citations, and >30m/input rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
