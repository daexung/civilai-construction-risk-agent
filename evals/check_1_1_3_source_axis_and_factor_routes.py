from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from evals.check_draft_executability import _source_numeric_values
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC_PATH = ROOT / "data/drafts/specs/건축/1-1-3.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
source_factors = {
    "필릿용접": {"p626-t1": {
        "5": "0.55", "6": "0.68", "7": "0.81", "8": "0.94", "9": "1.06", "10": "1.17",
        "11": "1.29", "12": "1.40", "13": "1.50", "14": "1.60", "15": "1.70", "16": "1.79",
        "17": "1.87", "18": "2.0", "19": "2.04", "20": "2.11",
    }},
    "V, K, X용접": {"p626-t2": {
        "6": "2.86", "7": "2.94", "8": "3.03", "9": "3.12", "10": "3.22", "11": "3.32",
        "12": "3.43", "13": "3.54", "14": "3.66", "15": "3.78", "16": "3.90", "18": "4.17",
        "20": "4.45", "22": "4.75", "24": "5.07", "26": "5.41", "28": "5.77", "30": "6.14",
        "32": "6.53", "34": "6.95", "35": "7.16", "40": "8.29", "45": "9.54", "50": "10.90",
        "55": "12.58", "60": "13.97", "65": "15.68", "70": "17.50", "75": "19.44", "80": "21.49",
    }},
}
base_bands = [(Fraction(0), Fraction("0.22")), (Fraction(20), Fraction("0.37")),
              (Fraction(30), Fraction("0.51")), (Fraction(40), Fraction("0.63")),
              (Fraction(50), Fraction("0.73")), (Fraction(60), Fraction("0.85")),
              (Fraction(70), Fraction("0.95")), (Fraction(80), Fraction("1.05")),
              (Fraction(90), Fraction("1.15")), (Fraction(100), Fraction("1.24")),
              (Fraction(110), Fraction("1.34")), (Fraction(120), Fraction("1.43")),
              (Fraction(130), Fraction("1.51")), (Fraction(140), Fraction("1.60")),
              (Fraction(150), Fraction("1.69")), (Fraction(160), Fraction("1.77")),
              (Fraction(170), Fraction("1.85")), (Fraction(180), Fraction("1.93")),
              (Fraction(190), Fraction("2.02")), (Fraction(200), Fraction("2.09"))]
routes = 0
for weld_type, by_table in source_factors.items():
    table_id, expected_cells = next(iter(by_table.items()))
    actual_cells = SPEC["tables"][[table["id"] for table in SPEC["tables"]].index(table_id)]["values"]["환산계수"]
    assert {key: actual_cells[key] for key in expected_cells} == expected_cells
    for thickness, coefficient in expected_cells.items():
        for member_type, multiplier in (("전용접부재", Fraction(1)), ("H형강부재", Fraction("0.73"))):
            inputs = {"member_type": member_type, "weld_type": weld_type,
                      "plate_thickness": thickness, "weld_length": "20", "quantity": "1"}
            result = per_unit(SPEC, inputs)
            assert result["status"] == "computed", (inputs, result)
            effective_length = Fraction(20) * Fraction(coefficient)
            eligible = [(threshold, amount) for threshold, amount in base_bands if threshold <= effective_length]
            expected_rate = max(eligible, key=lambda entry: entry[0])[1] * multiplier
            line = result["unit_lines"][0]
            assert Fraction(line["exact"]) == expected_rate, (inputs, line, expected_rate)
            assert any(cite.get("internal_id") == table_id and cite.get("column") == thickness
                       and Fraction(cite.get("value")) == Fraction(coefficient)
                       for cite in line["citations"]), (inputs, line["citations"])
            routes += 1
assert _source_numeric_values(SPEC, "plate_thickness") == ["5"]
chunks_path = ROOT / "data/processed/chunks.all.jsonl"
validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(chunks_path),
                          file_sha256(chunks_path))
assert validation["ok"], validation
audit = {
    "id": SPEC["id"], "status": "pass", "physical_pages": [625, 626], "printed_pages": [569, 570],
    "independently_checked_factor_cells": sum(len(cells) for by_table in source_factors.values()
                                               for cells in by_table.values()),
    "exact_factor_routes": routes, "baseline_rate_rule_checks": 20,
    "source_valid_input_sample": _source_numeric_values(SPEC, "plate_thickness"),
    "draft_validation": "pass", "all_rules_fully_verified": False,
    "visual_original_pages": ["evals/runtime_validation/source-p625-basic-weld.png",
                              "evals/runtime_validation/source-p626-basic-weld.png"],
    "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
    "execution_harness_note": "The former generic positive-number sample 100 was outside the factor-table domain; the evaluator now samples an exact declared source-axis value. Out-of-domain inputs remain rejected by runtime.",
}
out = ROOT / "evals/runtime_validation/per-unit-1-1-3-source-axis-factor-audit-2026-10-19.json"
out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: audit[k] for k in ("status", "independently_checked_factor_cells", "exact_factor_routes",
                                          "source_valid_input_sample", "draft_validation")}, ensure_ascii=False))
