"""Independent source-cell and exact calculation audit for mechanical 8-3-6."""
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
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402
from backend.agent.estimate import tools as estimate_tools  # noqa: E402
from backend.agent.nodes import select as select_node  # noqa: E402
from backend.agent.tools.source import citation as citation_runtime  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/8-3-6.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-8-3-6-radiator-rows-2026-10-19.json"

EXPECTED = {
    "주 철 재 바 닥 설 치 20절 이하": ("조", "1.10", "0.10"),
    "21절 이상": ("조", "1.50", "0.10"),
    "벽 걸 이 3절": ("조", "1.60", "0.20"),
    "천 장 달 기 3절": ("조", "2.50", "0.50"),
    "1m길트": ("본", "0.70", "0.10"),
    "콘백터 길이 1m 미만": ("조", "0.80", "0.10"),
    "콘백터 길이 1m 이상": ("조", "1.10", "0.10"),
    "베이스보드 1단형길이 2m 미만": ("단", "1.90", "0.20"),
    "2m이상": ("단", "2.40", "0.20"),
    "강판제 및 알루미늄제 방열기 1m 미만": ("조", "0.44", "0.06"),
    "강판제 및 알루미늄제 방열기 1m 이상": ("조", "0.60", "0.06"),
}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p754-t0")
    assert set(table["values"]) == set(EXPECTED)
    assert len(package["citations"]) == 25
    rows = []
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    for row, (unit, mechanic, helper) in EXPECTED.items():
        assert table["values"][row] == {"단위": f"인/{unit}", "배관공": mechanic, "보통인부": helper}
        for trade, value in (("배관공", mechanic), ("보통인부", helper)):
            citation = {"table_id": "p754-t0", "row": row, "column": trade, "value": value}
            assert check_table_citation(chunk_index, citation) is None, citation
            assert cite_table("p754-t0", row, trade, value).get("value") == value
        rows.append({"row": row, "unit": unit, "labor_rates": {"배관공": mechanic, "보통인부": helper}})

    doc = pymupdf.open(PDF_PATH)
    source_text = doc[753].get_text("text")
    assert "8-3-6" in source_text and "1m 이상" in source_text and "15%" in source_text and "20%" in source_text
    page_image = ROOT / "evals/runtime_validation/source-p754-radiator-8-3-6.png"
    assert page_image.exists()

    cases = []
    for row, (unit, mechanic, helper) in EXPECTED.items():
        extras = (2, 0) if row == "벽 걸 이 3절" else (0, 2) if row.startswith(("콘백터", "베이스보드", "2m이상")) else (0, 0)
        input_values = {"radiator_type": row, "quantity": "2",
                        "extra_sections": extras[0], "extra_tiers": extras[1]}
        result = per_unit(spec, input_values)
        assert result.get("status") == "computed", (input_values, result)
        multiplier = Fraction(1) + (Fraction(extras[0] * 15 + extras[1] * 20, 100))
        expected = {"배관공": Fraction(mechanic) * multiplier,
                    "보통인부": Fraction(helper) * multiplier}
        lines = {line["name"]: line for line in result["unit_lines"]}
        assert set(lines) == set(expected)
        for trade, value in expected.items():
            assert Fraction(lines[trade]["exact"]) == value, (input_values, trade, lines[trade], value)
            assert lines[trade]["citations"][0].get("internal_id") == "p754-t0"
            assert lines[trade]["citations"][0].get("row") == row
        assert result["unit_basis"]["per"] == f"1{unit}"
        cases.append({**input_values, "quantity_unit": unit, "multiplier": str(multiplier),
                      "expected_unit_rates": {k: str(v) for k, v in expected.items()}, "status": "computed"})

    panel = per_unit(spec, {"radiator_type": "패널 라디에이터", "quantity": "1",
                            "extra_sections": 0, "extra_tiers": 0})
    assert (panel.get("status") == "blocked" and panel.get("input") == ["radiator_type"]
            and any(c.get("internal_id") == "p754-x11" for c in panel.get("citations", []))), panel

    # Exercise the real estimate path: choose the work item first, then ask for
    # and validate the task-dependent physical quantity unit.
    hit = {"rank": 1, "section_no": "8-3-6", "division": "기계설비",
           "section": f"8-3-6 {spec['title']}", "page": 698,
           "table_id": "p754-t0", "text": spec["title"], "chunk_id": "p754-t0"}
    def values(**items):
        return {name: {"value": value, "evidence": str(value)} for name, value in items.items()}
    spec_map = {("기계설비", "8-3-6"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 698, "division": "기계설비"})), \
            patch.object(estimate_tools, "specs_by_section",
                         return_value=spec_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=spec_map):
        session = estimate_tools.new_estimate("방열기 설치")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(q["field"] == "radiator_type" for q in first.get("missing", [])), first
        estimate_tools.set_conditions(session, "길트형 방열기", values=values(radiator_type="1m길트"), source="answer")
        asked = estimate_tools.compute_labor(session)
        quantity_question = next(q for q in asked.get("missing", []) if q["field"] == "quantity")
        assert quantity_question.get("unit") == "본", quantity_question
        estimate_tools.set_conditions(session, "2본", quantity={"value": "2", "unit": "본", "evidence": "2본"}, source="text")
        estimate_tools.set_conditions(session, "해당 없음", values=values(extra_sections=0, extra_tiers=0), source="answer")
        end_to_end = estimate_tools.compute_labor(session)
        assert end_to_end.get("status") == "ok", end_to_end
        flow_lines = {line["name"]: line for line in end_to_end["data"]["unit_lines"]}
        assert {name: line["exact"] for name, line in flow_lines.items()} == {"배관공": "7/10", "보통인부": "1/10"}
        assert end_to_end["data"]["unit_basis"]["per"] == "1본"

    # The focused spec validator must accept every exact table and text citation.
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    audit = {
        "id": spec["id"], "status": "source_cells_and_supported_routes_verified",
        "source": {"physical_page": 754, "printed_page": 698,
                   "visual": "original PDF table visually checked; two separate 1m 이상 rows transcribed with their distinct parent labels",
                   "pdf_sha256": sha(PDF_PATH), "image": str(page_image.relative_to(ROOT)),
                   "image_sha256": sha(page_image), "unique_rate_cells_checked": 22,
                   "rows": rows},
        "runtime": {"computed_routes": len(cases), "routes": cases,
                    "estimate_flow": {"status": end_to_end["status"], "unit_question": "본",
                                      "unit_rates": {name: line["exact"] for name, line in flow_lines.items()},
                                      "unit_basis": end_to_end["data"]["unit_basis"]["per"]},
                    "panel_route": "blocked because source does not identify which convector length band applies"},
        "rule_scope": {"source_table_cells": "all 11 rows × 2 labor rates, independently compared",
                       "source_notes": ["extra wall-hung section: +15% each", "extra convector/baseboard tier: +20% each",
                                       "panel uses convector rate; length band unresolved"],
                       "all_rules_fully_verified": False},
        "spec_sha256": sha(SPEC_PATH), "runtime_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "cells": 22, "computed_routes": len(cases),
                      "panel": "blocked", "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
