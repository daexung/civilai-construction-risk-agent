"""Independent source-cell and task-dependent unit audit for mechanical 10-7-2."""
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

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/10-7-2.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p766-mech-10-7-2-sprinkler-panel.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-10-7-2-task-units-and-dashes-2026-10-19.json"

EXPECTED = {
    "7.5㎾ 이하": ("면", "2.580"),
    "11 ∼ 19㎾": ("면", "2.890"),
    "22㎾": ("면", "3.400"),
    "벨": ("개", "0.210"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(item for item in spec["tables"] if item["id"] == "p766-t3")
    assert set(table["values"]) == set(EXPECTED)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    source_chunk = chunk_index["p766-t3"]["text"]
    doc = pymupdf.open(PDF_PATH)
    source_text = doc[765].get_text("text")
    assert "10-7-2" in source_text and "스프링클러 전기설비설치" in source_text
    assert "면" in source_text and "배 관 공" in source_text and "보통인부" in source_text
    rows = []
    for row, (unit, rate) in EXPECTED.items():
        assert table["values"][row] == {"배관공": rate, "단위": unit, "보통인부": "-"}
        for column, value in (("단위", unit), ("배관공", rate), ("보통인부", "-")):
            citation = {"table_id": "p766-t3", "row": row, "column": column, "value": value}
            assert check_table_citation(chunk_index, citation) is None, citation
            assert cite_table("p766-t3", row, column, value).get("value") == value
        result = per_unit(spec, {"item": row, "quantity": "1"})
        assert result.get("status") == "computed", (row, result)
        assert [(line["name"], Fraction(line["exact"])) for line in result["unit_lines"]] == [
            ("배관공", Fraction(rate))], (row, result)
        assert result["unit_basis"]["per"] == f"1{unit}"
        excluded = [entry for entry in result["provenance"]["excluded_resources"]
                    if entry["trade"] == "보통인부"]
        assert len(excluded) == 1 and excluded[0]["citations"][0].get("value") == "-", (row, excluded)
        rows.append({"item": row, "unit": unit, "pipefitter_rate": rate,
                     "helper_source_cell": "-", "route": "computed", "helper": "excluded"})

    hit = {"rank": 1, "section_no": "10-7-2", "division": "기계설비",
           "section": f"10-7-2 {spec['title']}", "page": 710,
           "table_id": "p766-t3", "text": spec["title"], "chunk_id": "p766-t3"}
    spec_map = {("기계설비", "10-7-2"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 710, "division": "기계설비"})), \
            patch.object(estimate_tools, "specs_by_section", return_value=spec_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=spec_map):
        session = estimate_tools.new_estimate("스프링클러 펌프기동반")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(question["field"] == "item" for question in first.get("missing", [])), first
        estimate_tools.set_conditions(session, "7.5㎾ 이하", values={
            "item": {"value": "7.5㎾ 이하", "evidence": "7.5㎾ 이하"}}, source="answer")
        asked = estimate_tools.compute_labor(session)
        quantity_question = next(question for question in asked.get("missing", [])
                                 if question["field"] == "quantity")
        assert quantity_question.get("unit") == "면", quantity_question
        estimate_tools.set_conditions(session, "2면", quantity={
            "value": "2", "unit": "면", "evidence": "2면"}, source="text")
        end_to_end = estimate_tools.compute_labor(session)
        assert end_to_end.get("status") == "ok", end_to_end
        lines = end_to_end["data"]["unit_lines"]
        assert [(line["name"], Fraction(line["exact"])) for line in lines] == [
            ("배관공", Fraction("2.580"))], lines
        assert end_to_end["data"]["unit_basis"]["per"] == "1면"

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    audit = {
        "id": spec["id"], "status": "source_units_and_explicit_dashes_verified",
        "source": {"physical_page": 766, "printed_page": 710,
                   "visual": "original PDF p.710 image visually checked; four unit cells, four labor rates and four explicit helper dashes compared",
                   "pdf_sha256": sha(PDF_PATH), "image": str(IMAGE_PATH.relative_to(ROOT)),
                   "image_sha256": sha(IMAGE_PATH), "cells_checked": 12, "rows": rows},
        "extraction_repair": {"issue": "p766-t3 source chunk omitted the four visible 보통인부 dashes",
                              "repair": "restored exact row/column dash values in chunk text and spec; added cited exclusion rules"},
        "runtime": {"routes_computed": 4, "helper_routes_excluded_by_source_dash": 4,
                    "estimate_flow": {"status": end_to_end["status"], "quantity_question_unit": "면",
                                      "unit_rates": {line["name"]: line["exact"] for line in lines},
                                      "unit_basis": end_to_end["data"]["unit_basis"]["per"]},
                    "validation_issues": validation.get("issues", [])},
        "rule_scope": {"source_table_cells": "all 4 rows × unit + pipefitter rate + helper dash; 12 cells",
                       "source_note": "source note says ancillary piping/insulation are separate; this audit does not calculate those separate tasks",
                       "all_rules_fully_verified": False},
        "spec_sha256": sha(SPEC_PATH), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
        "runtime_fill_sha256": sha(ROOT / "backend/agent/nodes/fill.py"),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "cells": 12, "computed_routes": 4,
                      "source_dash_exclusions": 4, "estimate_unit": "면",
                      "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
