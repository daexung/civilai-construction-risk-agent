"""Source-derived calculation and scope checks for 2026 masonry section 2-1-1."""
from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402


def main() -> int:
    spec_path = next(path for path in (ROOT / "data/drafts/specs").rglob("*.json")
                     if any(field["name"] == "wall_thickness"
                            for field in json.loads(path.read_text(encoding="utf-8"))["draft"]["inputs"]))
    package = json.loads(spec_path.read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    assert spec["cost_rules"][0]["rate"] == "0.02"
    assert "9-1-1" in spec["not_calculated"][0]["item"] or "9-1-1" in spec["not_calculated"][0]["source"]
    source_path = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
    source = PdfReader(source_path).pages[634].extract_text() or ""
    compact = re.sub(r"\s+", "", source)
    assert "25" in compact and "9%" in compact and "2.5hr" in compact
    assert "75" in compact and "0.019" in compact

    fields = {field["name"]: field for field in spec["inputs"]}
    common = {"wall_thickness": fields["wall_thickness"]["allowed_values"][0],
              "work_height": fields["work_height"]["allowed_values"][0],
              "quantity": "227.5"}
    ordinary = adjusted_daily_crew(spec, {**common, "is_cavity_wall": False,
                                         "use_forklift": False}, labor_only=True)
    assert ordinary["status"] == "computed", ordinary
    assert ordinary["not_calculated"] == spec["not_calculated"]
    assert ordinary["daily_volume_m3"] == "25"
    assert ordinary["work_days"] == "9.1"
    assert ordinary["person_days"] == {"조적공": "27.3", "보통인부": "9.1"}
    materials = {line["name"]: line["exact"] for line in ordinary["unit_lines"]
                 if line["kind"] == "material"}
    # Independent source-table arithmetic: 227.5㎡ × 75 매/㎡ and × 0.019㎥/㎡.
    assert Fraction(materials["벽돌"]) == Fraction("227.5") * 75
    assert Fraction(materials["모르타르"]) == Fraction("227.5") * Fraction("0.019")

    cavity = adjusted_daily_crew(spec, {**common, "is_cavity_wall": True,
                                        "use_forklift": True}, labor_only=True)
    assert cavity["status"] == "computed", cavity
    assert cavity["daily_volume_m3"] == "22.75"  # 25 × (1 − 9/100)
    assert cavity["work_days"] == "10"
    assert cavity["person_days"] == {"조적공": "30", "보통인부": "0"}
    forklift = next(line for line in cavity["unit_lines"] if line["name"] == "지게차")
    assert Fraction(forklift["exact"]) * Fraction("227.5") == Fraction("25")
    note_citations = [cite for line in cavity["unit_lines"] for cite in line.get("citations", [])
                      if cite.get("row") == "비고"]
    assert any(cite.get("value") and "2.5hr" in re.sub(r"\s+", "", cite["value"])
               and "9%" in re.sub(r"\s+", "", cite["value"]) for cite in note_citations)

    outside = adjusted_daily_crew(spec, {**common,
        "work_height": fields["work_height"]["allowed_values"][-1],
        "is_cavity_wall": False, "use_forklift": False}, labor_only=True)
    assert outside["status"] == "blocked", outside
    print("PASS 원문 p.579 표·비고 대조; 기본/공간쌓기/지게차 계산, 재료량, 단위근거, >7.2m 차단")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
