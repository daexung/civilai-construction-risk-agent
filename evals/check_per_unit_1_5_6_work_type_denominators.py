"""Verify every source-defined work-type basis and the estimate quantity prompt."""
from __future__ import annotations
import hashlib
import json
import os
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.estimate import tools as estimate_tools  # noqa: E402
from backend.agent.nodes import select as select_node  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402
from backend.agent.tools.source import citation as citation_runtime  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/공통/1-5-6.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-5-6-work-type-denominators-2026-10-19.json"
EXPECTED = {
    "거푸집씻기": ("㎡", "㎥/㎡", "0.04"),
    "콘크리트혼합및양생": ("㎥", "㎥/㎥", "0.27"),
    "경량콘크리트혼합및양생": ("㎥", "㎥/㎥", "0.24"),
    "보통벽돌쌓기": ("매", "㎥/1,000매", "0.18"),
    "돌쌓기모르타르": ("㎡", "㎥/㎡", "0.06"),
    "돌씻기": ("㎡", "㎥/㎡", "0.17"),
    "미장": ("㎡", "㎥/㎡", "0.02"),
    "타일붙임모르타르": ("㎡", "㎥/㎡", "0.01"),
    "타일씻기": ("㎡", "㎥/㎡", "0.013"),
    "잡용수": ("㎥", "㎥", "사용량비의 40∼50%"),
}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p89-t0")
    assert set(table["values"]) == set(EXPECTED)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    doc = pymupdf.open(PDF_PATH)
    source_text = doc[88].get_text("text")
    assert "3. 공사용수" in source_text and "㎥/1,000" in source_text and "40" in source_text and "50%" in source_text

    routes = []
    for work_type, (unit, rate_unit, raw) in EXPECTED.items():
        assert table["values"][work_type] == {"수량": raw}
        cite = {"table_id": "p89-t0", "row": work_type, "column": "수량", "value": raw}
        assert check_table_citation(chunk_index, cite) is None, cite
        assert cite_table("p89-t0", work_type, "수량", raw).get("value") == raw
        if work_type == "잡용수":
            result = per_unit(spec, {"work_type": work_type, "quantity": "1"})
            assert result.get("status") == "blocked" and any(
                c.get("internal_id") == "p89-t0" for c in result.get("citations", [])), result
            routes.append({"work_type": work_type, "unit": unit, "source_rate_unit": rate_unit, "status": "blocked"})
            continue
        result = per_unit(spec, {"work_type": work_type, "quantity": "1"})
        assert result.get("status") == "computed", (work_type, result)
        line, = result["unit_lines"]
        divisor = 1000 if work_type == "보통벽돌쌓기" else 1
        expected_rate = Fraction(raw) / divisor
        assert Fraction(line["exact"]) == expected_rate, (work_type, line, expected_rate)
        assert line["unit"] == f"㎥/{unit}", (work_type, line["unit"])
        assert line["citations"][0].get("row") == work_type and line["citations"][0].get("value") == raw
        routes.append({"work_type": work_type, "unit": unit, "source_rate_unit": rate_unit,
                       "exact_rate_per_input_unit": str(expected_rate), "status": "computed"})

    # Real consultation path asks for work type before asking a quantity unit.
    hit = {"rank": 1, "section_no": "1-5-6", "division": "공통",
           "section": f"1-5-6 {spec['title']}", "page": 33,
           "table_id": "p89-t0", "text": spec["title"], "chunk_id": "p89-t0"}
    spec_map = {("공통", "1-5-6"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 33, "division": "공통"})), \
            patch.object(estimate_tools, "specs_by_section", return_value=spec_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=spec_map):
        session = estimate_tools.new_estimate("공사용수 산정")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(q["field"] == "work_type" for q in first.get("missing", [])), first
        estimate_tools.set_conditions(session, "거푸집 씻기", values={
            "work_type": {"value": "거푸집씻기", "evidence": "거푸집씻기"}}, source="answer")
        asked = estimate_tools.compute_labor(session)
        quantity_question = next(q for q in asked.get("missing", []) if q["field"] == "quantity")
        assert quantity_question.get("unit") == "㎡", quantity_question
        estimate_tools.set_conditions(session, "100㎡", quantity={"value": "100", "unit": "㎡", "evidence": "100㎡"}, source="text")
        final = estimate_tools.compute_labor(session)
        assert final.get("status") == "ok", final
        rate_line, = final["data"]["unit_lines"]
        assert rate_line["exact"] == "1/25" and rate_line["unit"] == "㎥/㎡", rate_line

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    image = ROOT / "evals/runtime_validation/source-p89-common-1-5-6-water.png"
    audit = {
        "id": spec["id"], "status": "source_rows_and_work_dependent_denominators_verified",
        "source": {"physical_page": 89, "printed_page": 33, "original_pdf_visual_review": True,
                   "image": str(image.relative_to(ROOT)), "image_sha256": sha(image), "pdf_sha256": sha(PDF_PATH),
                   "source_cells_checked": 10,
                   "rows": [{"work_type": k, "unit": v[0], "source_rate_unit": v[1], "value": v[2]} for k,v in EXPECTED.items()]},
        "runtime": {"source_routes": routes, "computed_routes": 9, "blocked_routes": 1,
                    "estimate_flow": {"status": final["status"], "asked_unit": "㎡",
                                      "rate": rate_line["exact"], "rate_unit": rate_line["unit"]}},
        "rule_scope": {"numeric_source_rows": 9, "symbolic_range_rows_blocked": 1,
                       "all_rules_fully_verified": False},
        "spec_sha256": sha(SPEC_PATH), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "source_cells": 10, "computed": 9, "blocked": 1,
                      "estimate_unit_prompt": "㎡", "audit": str(AUDIT.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
