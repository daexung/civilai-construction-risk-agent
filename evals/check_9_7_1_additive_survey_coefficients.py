from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/토목/9-7-1.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
base_rates = {"지적기사": Fraction("0.56"), "지적산업기사": Fraction("0.65"),
              "지적기능사": Fraction("0.30")}
land_rates = {"토지": Fraction("1.00"), "임야": Fraction("1.20")}
region_rates = {"면": Fraction("1.00"), "읍": Fraction("1.10"),
                "동 시": Fraction("1.30"), "동 구": Fraction("1.40")}
base_areas = {"토지": 1500, "임야": 5000}
routes = []
for land, land_rate in land_rates.items():
    base_area = base_areas[land]
    for area, increments, expected_area_factor in (
            (base_area, 0, Fraction(1)), (2 * base_area, 1, Fraction("1.3")),
            (2 * base_area + 1, 2, Fraction("1.4")), (7000 if land == "토지" else 25000, 4, Fraction("1.6"))):
        n = -(-(area - base_area) // base_area) if area > base_area else 0
        assert n == increments
        for region, region_rate in region_rates.items():
            expected_multiplier = 1 + (land_rate - 1) + (region_rate - 1) + (expected_area_factor - 1)
            result = per_unit(SPEC, {"parcel_count": "1", "area": str(area),
                                     "land_type": land, "region_type": region})
            assert result["status"] == "computed", result
            lines = {line["name"]: line for line in result["unit_lines"]}
            for trade, source_rate in base_rates.items():
                assert Fraction(lines[trade]["exact"]) == source_rate * expected_multiplier
                citations = lines[trade]["citations"]
                assert any(c.get("internal_id") == "p581-t0" and c.get("row") == "합계"
                           and Fraction(c.get("value")) == source_rate for c in citations)
                assert any(c.get("internal_id") == "p581-t2" and c.get("column") == land
                           and Fraction(c.get("value")) == land_rate for c in citations)
                assert any(c.get("internal_id") == "p582-t0" and c.get("column") == region
                           and Fraction(c.get("value")) == region_rate for c in citations)
                expected_area_cell = "0회" if n == 0 else "1회" if n == 1 else "2회이상"
                assert any(c.get("internal_id") == "p581-t1" and c.get("column") == expected_area_cell
                           for c in citations)
                assert any(c.get("internal_id") == "p582-x3"
                           and "합계" in str(c.get("quote", "")) for c in citations)
            routes.append({"land_type": land, "area_m2_per_parcel": area, "n": n,
                           "region": region, "area_coefficient": str(expected_area_factor),
                           "total_additive_coefficient": str(expected_multiplier),
                           "rates": {trade: str(rate * expected_multiplier)
                                     for trade, rate in base_rates.items()}})

# Independently reproduce the source's worked example: 7,000m2 unregistered
# 토지 in 구지역 gives area 1.60, region 1.40, land 1.00, and total 2.00.
example = next(route for route in routes if route["land_type"] == "토지"
               and route["area_m2_per_parcel"] == 7000 and route["region"] == "동 구")
assert example["total_additive_coefficient"] == "2"
two_parcels = {"parcel_count": "2", "area": "7000", "land_type": "토지", "region_type": "동 구"}
result = per_unit(SPEC, two_parcels)
priced = price_unit(SPEC, result["unit_lines"], select_rate_version("2026-10-19"),
                    two_parcels, "2026-10-19")
assert priced["status"] in ("PARTIAL", "OK")
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
assert validation["ok"], validation
audit = {
    "id": SPEC["id"], "status": "pass", "physical_pages": [581, 582], "printed_pages": [525, 526],
    "independent_numeric_source_cells": 12, "exact_coefficient_routes": len(routes),
    "worked_example": {"area_m2": 7000, "land": "토지", "region": "동 구",
                       "area_coefficient": "1.60", "region_coefficient": "1.40",
                       "land_coefficient": "1.00", "total_additive_coefficient": "2.00",
                       "labor_totals_per_parcel": {"지적기사": "1.12", "지적산업기사": "1.30", "지적기능사": "0.60"}},
    "two_parcel_price_status": priced["status"], "draft_validation": "pass",
    "all_rules_fully_verified": False,
    "remaining_scope": ["Source-declared machine expenses, consumable materials, control-point installation, island boat hire, and travel allowance remain separately accounted; rates are not specified in the section."],
    "visual_original_pages": ["evals/runtime_validation/source-p581-new-registration-survey.png",
                              "evals/runtime_validation/source-p582-new-registration-survey.png"],
    "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
}
out = ROOT / "evals/runtime_validation/per-unit-9-7-1-additive-survey-coefficients-audit-2026-10-19.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "pass", "independent_numeric_source_cells": audit["independent_numeric_source_cells"],
                  "exact_coefficient_routes": len(routes), "worked_example_multiplier": "2.00",
                  "draft_validation": "pass"}, ensure_ascii=False))
