"""Original PDF table and exact active calculation checks for maintenance 1-3-8."""
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
page870 = re.sub(r"\s+", "", pages[925].extract_text() or "")
page871 = re.sub(r"\s+", "", pages[926].extract_text() or "")
assert "1-3-8교량받침교체('21년신설)" in page870
for token in ("0.2ton이하", "0.3ton이하", "0.5ton이하", "1.0ton이하", "1.5ton이하", "1.5ton초과",
              "특별인부", "보통인부", "용접공", "크레인", "고소작업차", "0.54", "0.45", "0.38",
              "0.30", "0.25", "0.21", "0.26", "0.22", "0.18", "0.15"):
    assert token in page870, token
assert "교대및교각전체에비계및작업발판을설치한경우에는고소작업차의투입을제외한다" in page871
assert "25~50ton" in page871 and "3~5ton" in page871

package = json.loads((ROOT / "data/drafts/specs/유지관리/1-3-8.json").read_text(encoding="utf-8"))
spec = package["draft"]
executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
matrix = {
    "0.2ton 이하": ("p926-t0", 2, ["0.54", "0.45", "0.38"]),
    "0.3ton 이하": ("p926-t0", 2, ["0.45", "0.38", "0.31"]),
    "0.5ton 이하": ("p926-t0", 3, ["0.40", "0.34", "0.28"]),
    "1.0ton 이하": ("p926-t1", 3, ["0.30", "0.25", "0.21"]),
    "1.5ton 이하": ("p926-t1", 4, ["0.26", "0.22", "0.18"]),
    "1.5ton 초과": ("p926-t1", 4, ["0.22", "0.18", "0.15"]),
}
heights = ["20m 이하", "40m 이하", "40m 초과"]
count = 0
for weight, (table_id, special_count, rates) in matrix.items():
    for height, rate in zip(heights, rates):
        for scaffold in (False, True):
            inputs = {"bearing_weight": weight, "pier_height": height,
                      "quantity": "2", "scaffold_installed": scaffold}
            result = adjusted_daily_crew(spec, inputs, labor_only=True)
            assert result["status"] == "computed", (inputs, result)
            days = Fraction(2) / Fraction(rate)
            assert Fraction(result["work_days"]) == days
            assert Fraction(result["person_days"]["특별인부"]) == days * special_count
            assert Fraction(result["person_days"]["보통인부"]) == days
            assert Fraction(result["person_days"]["용접공"]) == days
            assert Fraction(result["equipment_days"]["크레인"]) == days
            platform = result["equipment_days"].get("고소작업차", "0")
            assert Fraction(platform) == (0 if scaffold else days)
            src = result["provenance"]["daily_volume_m3"]["base_output"]
            assert (src["table"], src["row"], src["column"], src["value"]) == (
                table_id, weight, height, rate)
            expected_cells = {"특별인부": str(special_count), "보통인부": "1", "용접공": "1",
                              "크레인": "1"}
            if not scaffold:
                expected_cells["고소작업차"] = "1"
            for name, value in expected_cells.items():
                line = next(line for line in result["unit_lines"] if line["name"] == name)
                citation = next(c for c in line["citations"] if c.get("internal_id") == table_id)
                assert (citation.get("row"), citation.get("column"), citation.get("value")) == (
                    weight, name, value), (inputs, name, citation)
            if scaffold and weight == "0.2ton 이하" and height == "20m 이하" and spec["id"] in executable:
                active = compute({"spec_id": spec["id"], "inputs": inputs})
                assert active["status"] == "COMPUTED", active
                assert Fraction(active["result"]["work_days"]) == days
            count += 1

assert spec["cost_rules"][0]["rate"] == "0.05"
assert len(package["draft"]["not_calculated"]) == 2
print(json.dumps({"status": "pass", "source_productivity_cells": 6 * 3,
                  "exact_quantity_cases": count,
                  "scope": "PDF 870~871쪽 중량·높이 2차원 생산량, 작업조, 크레인/고소작업차, 비계 조건",
                  "not_verified": ["price calculation", "consultation", "multi-item aggregation", "Excel"]},
                 ensure_ascii=False, indent=2))
