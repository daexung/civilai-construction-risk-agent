"""PDF-cell and exact runtime check for maintenance 2-1-10 type/range routes."""
from __future__ import annotations

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.nodes.compute import compute  # noqa: E402
from pypdf import PdfReader  # noqa: E402

PDF = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
pages = PdfReader(PDF).pages
page879 = re.sub(r"\s+", "", pages[934].extract_text() or "")
page880 = re.sub(r"\s+", "", pages[935].extract_text() or "")
assert "2-1-10소파보수(도로복구)" in page879
for token in ("포장공인4", "보통인부인2", "85", "35", "15", "굴착기+대형브레이커", "커터(콘크리트및아스팔트용)",
              "로더(타이어)", "진동롤러(진동+타이어)", "진동롤러(핸드가이드식)", "플레이트콤팩터",
              "아스팔트스프레이어", "트럭"):
    assert token in page879, token
for token in ("A-Type6㎡이하12㎡이하24㎡이하36㎡이하36㎡초과시공량할증계수0.890.941.001.061.13",
              "B-Type4㎡이하8㎡이하16㎡이하24㎡이하24㎡초과시공량할증계수0.890.941.001.061.13",
              "C-Type2㎡이하4㎡이하8㎡이하12㎡이하12㎡초과시공량할증계수0.890.941.001.061.13"):
    assert token in page880, token

package = json.loads((ROOT / "data/drafts/specs/유지관리/2-1-10.json").read_text(encoding="utf-8"))
spec = package["draft"]
executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
table_map = {table["id"]: table for table in spec["tables"]}
cases = {
    "A Type": ("A-Type", "p936-t0", 85, [6, 12, 24, 36], ["0.89", "0.94", "1.00", "1.06", "1.13"]),
    "B Type": ("B-Type", "p936-t1", 35, [4, 8, 16, 24], ["0.89", "0.94", "1.00", "1.06", "1.13"]),
    "C Type": ("C-Type", "p936-t2", 15, [2, 4, 8, 12], ["0.89", "0.94", "1.00", "1.06", "1.13"]),
}
checked = 0
for site_type, (prefix, table_id, base, bounds, factors) in cases.items():
    points = [Fraction(1, 10)]
    for bound in bounds:
        points.extend([Fraction(bound), Fraction(bound) + Fraction(1, 100)])
    for area in points:
        band = next((i for i, bound in enumerate(bounds) if area <= bound), len(bounds))
        raw_factor = factors[band]
        inputs = {"site_type": site_type, "area_per_location": str(area), "total_area": "100"}
        result = adjusted_daily_crew(spec, inputs, labor_only=True)
        assert result["status"] == "computed", (site_type, area, result)
        expected_days = Fraction(100) / (Fraction(base) * Fraction(raw_factor))
        assert Fraction(result["work_days"]) == expected_days
        assert Fraction(result["person_days"]["포장공"]) == expected_days * 4
        assert Fraction(result["person_days"]["보통인부"]) == expected_days * 2
        expected_col = list(table_map[table_id]["values"]["시공량 할증계수"])[band]
        provenance = result["provenance"]["daily_volume_m3"]
        assert provenance["base_output"]["column"] == f"{prefix} 시공량(㎡)"
        assert (provenance["coefficients"][0]["table"], provenance["coefficients"][0]["column"],
                provenance["coefficients"][0]["value"]) == (table_id, expected_col, raw_factor)
        if area == bounds[0] and spec["id"] in executable:
            active = compute({"spec_id": spec["id"], "inputs": inputs})
            assert active["status"] == "COMPUTED", (site_type, active)
            assert Fraction(active["result"]["work_days"]) == expected_days
        checked += 1

print(json.dumps({"status": "pass", "original_page_cells_checked": 18,
                  "exact_calculator_boundary_cases": checked,
                  "scope": "PDF 879~880쪽 표 2-1-10 Type 행·계수 구간·직종 인일·실행기 경로",
                  "not_verified": ["consultation", "multi-item aggregation", "Excel", "local price mapping"]},
                 ensure_ascii=False, indent=2))
