"""Source-derived checks for soil compaction by plate compactor and rammer."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("3-4-3.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    source = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[130].extract_text() or ""
    for value in ("18", "11", "24", "15", "14", "9", "20", "13", "1.5ton", "80kg"):
        assert value in source, value

    equipment = next(x for x in spec["inputs"] if x["name"] == "equipment")["allowed_values"]
    thicknesses = next(x for x in spec["inputs"] if x["name"] == "compaction_thickness")["allowed_values"]
    soils = next(x for x in spec["inputs"] if x["name"] == "soil_type")["allowed_values"]
    source_rates = [[[18, 11], [24, 15]], [[14, 9], [20, 13]]]
    for ei, machine in enumerate(equipment):
        for ti, thickness in enumerate(thicknesses):
            for si, soil in enumerate(soils):
                rate = source_rates[ei][ti][si]
                result = adjusted_daily_crew(spec, {"equipment": machine, "compaction_thickness": thickness,
                                                     "soil_type": soil, "volume": "180", "is_sand": False},
                                             labor_only=True)
                assert result["status"] == "computed", result
                days = Fraction(180, rate)
                assert Fraction(result["daily_volume_m3"]) == rate
                assert Fraction(result["work_days"]) == days
                assert set(Fraction(v) for v in result["person_days"].values()) == {days}
                assert {k: Fraction(v) for k, v in result["equipment_days"].items()} == {machine: days}
                assert result["provenance"]["daily_volume_m3"]["base_output"]["citations"]

    sand = adjusted_daily_crew(spec, {"equipment": equipment[0], "compaction_thickness": thicknesses[0],
                                      "soil_type": soils[0], "volume": "180", "is_sand": True},
                               labor_only=True)
    assert sand["status"] == "blocked", sand
    invalid = adjusted_daily_crew(spec, {"equipment": "outside source scope", "compaction_thickness": thicknesses[0],
                                         "soil_type": soils[0], "volume": "180", "is_sand": False},
                                  labor_only=True)
    assert invalid["status"] == "rejected", invalid
    print("PASS p.75 eight equipment/thickness/soil source combinations, crew/equipment days, sand block, and invalid scope rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
