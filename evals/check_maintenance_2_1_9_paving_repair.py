"""Coordinate-independent PDF text and exact-runtime checks for maintenance 2-1-9."""
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
spec = json.loads((ROOT / "data/drafts/specs/유지관리/2-1-9.json").read_text(encoding="utf-8"))["draft"]
page878 = re.sub(r"\s+", "", pages[933].extract_text() or "")
page879 = re.sub(r"\s+", "", pages[934].extract_text() or "")
assert "2-1-9소파보수(포장복구)" in page878
assert "포장공인3" in page878 and "보통인부인1" in page878
assert "굴착기0.18㎥대111" in page878
assert "로더(타이어)0.57㎥대11-" in page878
assert "진동롤러(진동+타이어)2.5ton대11-" in page878
assert "진동롤러(핸드가이드식)0.7ton대--1" in page878
assert "플레이트콤팩터1.5ton대--1" in page878
assert "아스팔트스프레이어400ℓ대111" in page878
assert "트럭2.5ton대222" in page878
assert "A-Type8㎡이하16㎡이하24㎡이하48㎡이하48㎡초과시공량할증계수0.850.921.001.091.18" in page878
assert "B-Type5㎡이하10㎡이하20㎡이하30㎡이하30㎡초과시공량할증계수0.850.921.001.091.18" in page879
assert "C-Type3㎡이하6㎡이하12㎡이하18㎡이하18㎡초과시공량할증계수0.850.921.001.091.18" in page879

# Each row is read from independently declared source-transcribed values, then compared
# with the real calculator output and its selected table-cell citation.
cases = {
    "A Type": ("A-Type", "p934-t4", 110, [8, 16, 24, 48], ["0.85", "0.92", "1.00", "1.09", "1.18"]),
    "B Type": ("B-Type", "p935-t0", 45, [5, 10, 20, 30], ["0.85", "0.92", "1.00", "1.09", "1.18"]),
    "C Type": ("C-Type", "p935-t1", 20, [3, 6, 12, 18], ["0.85", "0.92", "1.00", "1.09", "1.18"]),
}
table_map = {table["id"]: table for table in spec["tables"]}
checked = 0
for repair_type, (prefix, table_id, base, bounds, factors) in cases.items():
    points = [Fraction(1, 10)]
    for bound in bounds:
        points.extend([Fraction(bound), Fraction(bound) + Fraction(1, 100)])
    for area in points:
        band = next((i for i, bound in enumerate(bounds) if area <= bound), len(bounds))
        raw_factor = factors[band]
        inputs = {
            "repair_type": repair_type, "area_per_location": str(area), "total_area": "100",
        }
        result = adjusted_daily_crew(spec, inputs, labor_only=True)
        assert result["status"] == "computed", (repair_type, area, result)
        expected_daily = Fraction(base) * Fraction(raw_factor)
        expected_days = Fraction(100) / expected_daily
        assert Fraction(result["work_days"]) == expected_days
        assert Fraction(result["person_days"]["포장공"]) == expected_days * 3
        assert Fraction(result["person_days"]["보통인부"]) == expected_days
        expected_coefficient_column = list(table_map[table_id]["values"]["시공량 할증계수"])[band]
        provenance = result["provenance"]["daily_volume_m3"]
        assert provenance["base_output"]["column"] == f"{prefix} 시공량(㎡)"
        coefficient = provenance["coefficients"][0]
        assert (coefficient["table"], coefficient["row"], coefficient["column"], coefficient["value"]) == (
            table_id, "시공량 할증계수", expected_coefficient_column, raw_factor)
        if area == bounds[0]:
            active = compute({"spec_id": spec["id"], "inputs": inputs})
            assert active["status"] == "COMPUTED", (repair_type, active)
            assert Fraction(active["result"]["work_days"]) == expected_days
        checked += 1

print(json.dumps({"status": "pass", "source_table_rows_and_rate_cells": 3 + 2 + 2,
                  "daily_crew_cases": checked, "scope": "PDF 878~879쪽 2-1-9 표 행·구간 선택·작업일수·직종 인일",
                  "not_verified": ["상담 문답", "다중공종 집계", "Excel", "price mapping"]},
                 ensure_ascii=False, indent=2))
