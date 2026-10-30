"""PDF and exact calculator checks for all supported 2-1-15 line-marking routes."""
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
from backend.agent.tools.calc.price import price_unit  # noqa: E402
from pypdf import PdfReader  # noqa: E402

PDF = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
pages = PdfReader(PDF).pages
texts = {n: re.sub(r"\s+", "", pages[n - 1].extract_text() or "") for n in (938, 939, 940)}
assert "2-1-15차선도색" in texts[938]
assert "2.수용성형페인트수동식" in texts[938]
for token in ("특별인부인2", "보통인부인2", "600", "300", "228", "108", "트럭4.5ton대1"):
    assert token in texts[938], token
for token in ("3.수용성형페인트기계식", "특별인부인1", "보통인부인1", "4,000", "2,000", "라인마커트럭10㎞/hr대1",
              "트럭2.5ton대1", "4.융착식도료수동식", "500", "250", "190", "90", "트럭4.5ton", "트럭2.5ton"):
    assert token in texts[939], token
for token in ("5.상온경화형플라스틱도료구동식", "520", "260", "200", "95", "트럭2.5ton대2"):
    assert token in texts[940], token

package = json.loads((ROOT / "data/drafts/specs/유지관리/2-1-15.json").read_text(encoding="utf-8"))
spec = package["draft"]
executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
method_tables = {
    "차선 밑그림": ("p938-t1", {"실선": 600, "파선": 300, "횡단보도, 주차장": 228, "문자, 기호": 108}, 2, 2,
                     {"트럭(2.5ton)": "1"}),
    "수용성형 페인트 수동식": ("p938-t2", {"실선": 600, "파선": 300, "횡단보도, 주차장": 228, "문자, 기호": 108}, 2, 2,
                             {"트럭(4.5ton)": "1"}),
    "수용성형 페인트 기계식": ("p939-t0", {"실선": 4000, "파선": 2000}, 1, 1,
                             {"라인마커트럭(10㎞/hr)": "1", "트럭(2.5ton)": "1"}),
    "융착식 도료 수동식": ("p939-t1", {"실선": 500, "파선": 250, "횡단보도, 주차장": 190, "문자, 기호": 90}, 2, 2,
                           {"트럭(4.5ton, 용해기 운반)": "1", "트럭(2.5ton, 자재·경장비 운반)": "1"}),
    "상온경화형 플라스틱 도료 구동식": ("p940-t2", {"실선": 520, "파선": 260, "횡단보도, 주차장": 200, "문자, 기호": 95}, 2, 2,
                                 {"트럭(2.5ton)": "2"}),
}
checked = 0
for method, (table_id, rates, special, general, equipment) in method_tables.items():
    for line_type, rate in rates.items():
        inputs = {"method": method, "line_type": line_type, "quantity": "100", "surface_obstacle": False}
        result = adjusted_daily_crew(spec, inputs, labor_only=True)
        assert result["status"] == "computed", (inputs, result)
        days = Fraction(100, rate)
        assert Fraction(result["work_days"]) == days
        assert Fraction(result["person_days"]["특별인부"]) == days * special
        assert Fraction(result["person_days"]["보통인부"]) == days * general
        for name, count in equipment.items():
            assert Fraction(result["equipment_days"][name]) == days * Fraction(count)
        source = result["provenance"]["daily_volume_m3"]["base_output"]
        assert (source["table"], source["row"], Fraction(source["value"].replace(",", ""))) == (
            table_id, "보통인부", Fraction(rate))
        if line_type == "실선":
            priced = price_unit(spec, result["unit_lines"], None, inputs)
            expected_cost = {
                "수용성형 페인트 수동식": "0.03",
                "융착식 도료 수동식": "0.10",
                "상온경화형 플라스틱 도료 구동식": "0.02",
            }.get(method)
            if expected_cost:
                assert any(line.get("rate") == expected_cost for line in priced["cost_lines"]), (method, priced)
            else:
                assert not priced["cost_lines"], (method, priced["cost_lines"])
            separated = [line["name"] for line in priced["unpriced"]
                         if line["name"] == "탑승형 라인마커 기계경비 별도 계상"]
            assert bool(separated) == (method == "상온경화형 플라스틱 도료 구동식"), (method, separated)
        if method == "차선 밑그림" and line_type == "실선" and spec["id"] in executable:
            active = compute({"spec_id": spec["id"], "inputs": inputs})
            assert active["status"] == "COMPUTED" and Fraction(active["result"]["work_days"]) == days
        checked += 1

for method in list(method_tables)[1:]:
    blocked = adjusted_daily_crew(spec, {"method": method, "line_type": "실선", "quantity": "100",
                                         "surface_obstacle": True}, labor_only=True)
    assert blocked["status"] == "blocked", (method, blocked)
    assert blocked.get("citations"), (method, blocked)
missing = adjusted_daily_crew(spec, {"method": "수용성형 페인트 기계식", "line_type": "횡단보도, 주차장",
                                     "quantity": "100", "surface_obstacle": False}, labor_only=True)
assert missing["status"] == "blocked" and missing.get("citations"), missing

costs = {(rule["when"]["method"], rule["rate"]) for rule in spec["cost_rules"]}
assert costs == {("수용성형 페인트 수동식", "0.03"), ("융착식 도료 수동식", "0.10"),
                 ("상온경화형 플라스틱 도료 구동식", "0.02")}
print(json.dumps({"status": "pass", "supported_source_routes": checked,
                  "blocked_policy_or_missing_cells": 5,
                  "scope": "PDF 882~884쪽 다섯 공법, line_type별 일당시공량·인원·장비, 보류 조건",
                  "not_verified": ["dynamic cost amount against wage prices", "supply/material pricing",
                                   "consultation", "multi-item aggregation", "Excel"]},
                 ensure_ascii=False, indent=2))
