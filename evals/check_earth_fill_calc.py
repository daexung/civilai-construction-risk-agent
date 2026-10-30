"""Source-derived checks for compacted and loose earth fill."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("3-4-1.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    pdf = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
    pages = (pdf.pages[129].extract_text() or "") + (pdf.pages[130].extract_text() or "")
    for value in ("1,150", "770", "1,300", "16,000", "10.0ton", "32ton"):
        assert value in pages, value

    choices = next(x for x in spec["inputs"] if x["name"] == "compaction_type")["allowed_values"]
    expected = [
        (1150, {"모터그레이더(일반용)": 1, "진동롤러(자주식)": 1, "굴착기": 1,
                "물탱크(살수차)": Fraction(1, 2)}, True),
        (770, {"모터그레이더(일반용)": 1, "진동롤러(자주식)": 1, "굴착기": 1,
               "물탱크(살수차)": Fraction(1, 2)}, True),
        (1300, {"불도저": 1}, False),
    ]
    for choice, (daily_output, equipment_counts, has_crew) in zip(choices, expected):
        result = adjusted_daily_crew(spec, {"compaction_type": choice, "volume": "2600"}, labor_only=True)
        assert result["status"] == "computed", result
        days = Fraction(2600, daily_output)
        assert Fraction(result["daily_volume_m3"]) == daily_output
        assert Fraction(result["work_days"]) == days
        assert {k: Fraction(v) for k, v in result["equipment_days"].items()} == {
            k: days * count for k, count in equipment_counts.items()}
        if has_crew:
            assert list(result["person_days"].values()) == [str(days)]
        else:
            assert result["person_days"] == {}
        assert result["provenance"]["daily_volume_m3"]["base_output"]["citations"]

    for inputs in ({"compaction_type": choices[0], "volume": "0"},
                   {"compaction_type": "outside source range", "volume": "100"}):
        assert adjusted_daily_crew(spec, inputs, labor_only=True)["status"] == "rejected"
    print("PASS p.74-75 compacted/loose output, crew/equipment counts, table citations, and invalid input rejection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
