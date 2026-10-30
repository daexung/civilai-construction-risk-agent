"""Check source-table axes after lookup-only applicability conditions are enforced."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def main() -> int:
    pdf = pymupdf.open(PDF)

    # 2-2-4 printed p.40: the period is a column axis; the support-type input
    # is a separate applicability gate from [주], not an axis in the table.
    p224_path = ROOT / "data/drafts/specs/공통/2-2-4.json"
    p224 = json.loads(p224_path.read_text(encoding="utf-8"))["draft"]
    page = pdf[95]
    page_text = page.get_text()
    for token in ["1개월", "3개월", "6개월", "12개월", "4", "7", "11", "21", "손율(%)"]:
        assert token in page_text, ("2-2-4 PDF source token", token)
    expected = {"1개월": "4", "3개월": "7", "6개월": "11", "12개월": "21"}
    table = p224["tables"][0]
    assert table["values"] == {"손율(%)": expected}
    lookups = 0
    for support in ["강관 동바리", "시스템 동바리", "알루미늄 폼 동바리"]:
        for duration, rate in expected.items():
            result = lookup(p224, {"duration": duration, "support_type": support})
            assert result["status"] == "computed" and result["value"] == rate, (support, duration, result)
            lookups += 1
        assert lookup(p224, {"duration": "12개월", "support_type": support})["value"] == "21"
    assert lookup(p224, {"duration": "3개월", "support_type": "기타"})["status"] == "blocked"

    # 3-11-2 PDF p.86: bucket and work-condition are the two table axes;
    # total volume is a threshold checked by the source note, not a table axis.
    p311_path = ROOT / "data/drafts/specs/공통/3-11-2.json"
    p311 = json.loads(p311_path.read_text(encoding="utf-8"))["draft"]
    source_matrix = pdf[141].find_tables().tables[1].extract()
    assert source_matrix[2][1:] == ["1.0㎥ 시공량", "880", "700", "㎥"]
    assert source_matrix[3][1:4] == ["0.6㎥ 시공량", "515", "410"]
    expected_matrix = {"1.0㎥ 시공량": {"일당시공량 양호": "880", "일당시공량 보통": "700"},
                       "0.6㎥ 시공량": {"일당시공량 양호": "515", "일당시공량 보통": "410"}}
    assert p311["tables"][0]["values"] == expected_matrix
    volume_cells = 0
    for bucket, conditions in expected_matrix.items():
        for condition, value in conditions.items():
            good = lookup(p311, {"bucket_capacity": bucket, "condition": condition, "total_volume": 10000})
            assert good["status"] == "computed" and good["value"] == value, (bucket, condition, good)
            blocked = lookup(p311, {"bucket_capacity": bucket, "condition": condition, "total_volume": 9999})
            assert blocked["status"] == "blocked", (bucket, condition, blocked)
            volume_cells += 1

    chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
    for spec_path in [p224_path, p311_path]:
        validation = validate_one(spec_path, ROOT / "data/drafts/specs", chunks, None)
        assert validation["ok"], validation
    print(json.dumps({"status": "pass", "2-2-4_source_cells": 4, "2-2-4_lookup_cases": lookups,
                      "2-2-4_out_of_scope_support": "blocked", "3-11-2_source_cells": 4,
                      "3-11-2_volume_gates_checked": volume_cells * 2,
                      "3-11-2_open_fuel_surcharge": "retained; not resolved here",
                      "citation_preflight": "both pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
