"""Source-cell, mixed-unit route, and citation audit for mechanical 10-8-1."""
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
from backend.agent.estimate import tools as estimate_tools  # noqa: E402
from backend.agent.nodes import select as select_node  # noqa: E402
from backend.agent.tools.source import citation as citation_runtime  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/10-8-1.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p767-mech-10-8-1-extinguisher-system.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-10-8-1-mixed-item-units-2026-10-19.json"

# Independent transcription from printed p.711: (quantity unit, rate, source row prefix).
EXPECTED = {
    "선택밸브_ø 25이하": ("개", "0.52", "선택밸브 | 규격 ø 25이하"),
    "선택밸브_32이하": ("개", "0.82", "선택밸브 | 규격 32이하"),
    "선택밸브_40이하": ("개", "0.82", "선택밸브 | 규격 40이하"),
    "선택밸브_50이하": ("개", "0.82", "선택밸브 | 규격 50이하"),
    "선택밸브_65이하": ("개", "1.03", "선택밸브 | 규격 65이하"),
    "선택밸브_80이하": ("개", "1.24", "선택밸브 | 규격 80이하"),
    "선택밸브_100이하": ("개", "2.06", "선택밸브 | 규격 100이하"),
    "선택밸브_125이하": ("개", "2.06", "선택밸브 | 규격 125이하"),
    "선택밸브_150이하": ("개", "2.06", "선택밸브 | 규격 150이하"),
    "가스분사헤드_노출형": ("개", "0.21", "가스분사헤드 | 규격 노출형"),
    "가스분사헤드_매입형": ("개", "0.41", "가스분사헤드 | 규격 매입형"),
    "용기지지대_5본 이하": ("조", "1.03", "용기지지대 | 규격 5본 이하"),
    "용기지지대_6 ∼ 10본": ("조", "1.55", "용기지지대 | 규격 6 ∼ 10본"),
    "용기지지대_11 ∼ 20본": ("조", "2.06", "용기지지대 | 규격 11 ∼ 20본"),
    "용기집합함_5본 이하": ("조", "0.42", "용기집합함 | 규격 5본 이하"),
    "용기집합함_6 ∼ 10본": ("조", "0.72", "용기집합함 | 규격 6 ∼ 10본"),
    "기동용기": ("조", "0.62", "기동용기"),
    "수동기동함": ("개", "0.41", "수동기동함"),
    "압력스위치": ("개", "0.31", "압력스위치"),
    "역지밸브": ("개", "0.10", "역지밸브"),
    "배전반_1 ∼ 3실용": ("면", "2.06", "배전반 | 규격 1 ∼ 3실용"),
    "배전반_4 ∼ 6실용": ("면", "3.09", "배전반 | 규격 4 ∼ 6실용"),
    "단자함_대형": ("면", "0.41", "단자함 | 규격 대형"),
    "단자함_소형": ("면", "0.21", "단자함 | 규격 소형"),
    "가스방출표시등함": ("개", "0.41", "가스방출표시등함"),
    "모터사이렌": ("개", "0.31", "모터사이렌"),
    "벨": ("개", "0.21", "벨"),
}
SOURCE_UNIT_MARKERS = {
    "선택밸브_32이하": "〃", "선택밸브_40이하": "〃", "선택밸브_50이하": "〃",
    "선택밸브_65이하": "〃", "선택밸브_80이하": "〃", "선택밸브_100이하": "〃",
    "선택밸브_125이하": "〃", "선택밸브_150이하": "〃", "가스분사헤드_매입형": "〃",
    "용기지지대_6 ∼ 10본": "〃", "용기지지대_11 ∼ 20본": "〃",
    "용기집합함_6 ∼ 10본": "〃", "배전반_4 ∼ 6실용": "〃", "단자함_소형": "〃",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_estimate_flow(spec: dict, item: str, unit: str, expected_rate: str) -> dict:
    hit = {"rank": 1, "section_no": "10-8-1", "division": "기계설비",
           "section": f"10-8-1 {spec['title']}", "page": 711,
           "table_id": "p767-t0", "text": spec["title"], "chunk_id": "p767-t0"}
    spec_map = {("기계설비", "10-8-1"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 711, "division": "기계설비"})), \
            patch.object(estimate_tools, "specs_by_section", return_value=spec_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=spec_map):
        session = estimate_tools.new_estimate("소화약제 설비 설치")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(question["field"] == "item_and_spec" for question in first.get("missing", [])), first
        estimate_tools.set_conditions(session, item, values={
            "item_and_spec": {"value": item, "evidence": item}}, source="answer")
        asked = estimate_tools.compute_labor(session)
        quantity_question = next(question for question in asked.get("missing", [])
                                 if question["field"] == "quantity")
        assert quantity_question.get("unit") == unit, quantity_question
        estimate_tools.set_conditions(session, f"2{unit}", quantity={
            "value": "2", "unit": unit, "evidence": f"2{unit}"}, source="text")
        result = estimate_tools.compute_labor(session)
        assert result.get("status") == "ok", result
        lines = result["data"]["unit_lines"]
        assert [(line["name"], Fraction(line["exact"])) for line in lines] == [
            ("배관공", Fraction(expected_rate))], lines
        assert result["data"]["unit_basis"]["per"] == f"1{unit}"
        return {"status": result["status"], "quantity_question_unit": unit,
                "unit_rate": lines[0]["exact"], "unit_basis": result["data"]["unit_basis"]["per"]}


def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(item for item in spec["tables"] if item["id"] == "p767-t0")
    assert set(table["values"]) == set(EXPECTED)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    source_chunk = chunk_index["p767-t0"]["text"]
    source_text = pymupdf.open(PDF_PATH)[766].get_text("text")
    assert "10-8-1" in source_text and "소화약제 소화설비설치" in source_text
    assert "인/개" in source_text and "인/조" in source_text and "인/면" in source_text
    assert len(EXPECTED) == 27
    routes = []
    for row, (unit, rate, source_prefix) in EXPECTED.items():
        source_unit = SOURCE_UNIT_MARKERS.get(row, f"인/{unit}")
        source_signature = f"{source_prefix} | 단위 {source_unit} | 배관공 {rate}"
        assert source_signature in source_chunk, (row, source_signature)
        assert table["values"][row]["배관공"] == rate
        assert table["values"][row]["단위"] == f"인/{unit}"
        row_results = per_unit(spec, {"item_and_spec": row, "quantity": "1"})
        assert row_results.get("status") == "computed", (row, row_results)
        assert len(row_results["unit_lines"]) == 1
        line = row_results["unit_lines"][0]
        assert line["name"] == "배관공" and Fraction(line["exact"]) == Fraction(rate)
        assert line["unit"] == f"인/{unit}"
        assert line["citations"][0].get("row") == source_prefix
        for column, value in (("단위", f"인/{unit}"), ("배관공", rate)):
            citation = {"table_id": "p767-t0", "row": source_prefix,
                        "column": column, "value": value}
            assert check_table_citation(chunk_index, citation) is None, citation
        routes.append({"item": row, "unit": unit, "rate": rate,
                       "citation_row": source_prefix, "status": row_results["status"]})

    # Exercise all three physical quantity dimensions through the estimate flow.
    representative = {
        "개": ("선택밸브_ø 25이하", "0.52"),
        "조": ("용기지지대_6 ∼ 10본", "1.55"),
        "면": ("배전반_1 ∼ 3실용", "2.06"),
    }
    estimate_flows = {unit: run_estimate_flow(spec, item, unit, rate)
                      for unit, (item, rate) in representative.items()}
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    audit = {
        "id": spec["id"], "status": "all_mixed_item_units_and_source_rates_verified",
        "source": {"physical_page": 767, "printed_page": 711,
                   "visual": "original PDF p.711 image visually checked; all 27 item rows, quantity denominators and labor cells compared to extracted source lines",
                   "pdf_sha256": sha(PDF_PATH), "image": str(IMAGE_PATH.relative_to(ROOT)),
                   "image_sha256": sha(IMAGE_PATH), "source_rows_checked": 27,
                   "unit_and_labor_cells_checked": 54, "rows": routes},
        "runtime": {"computed_routes": len(routes), "estimate_flows_by_unit": estimate_flows,
                    "validation_issues": validation.get("issues", [])},
        "rule_scope": {"source_table_cells": "27 rows × explicit denominator + labor rate; 54 source cells",
                       "source_note": "Extinguisher agent/capsule mounting is stated separately by source note ③ and remains outside this installation table.",
                       "all_rules_fully_verified": False},
        "spec_sha256": sha(SPEC_PATH), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "runtime_fill_sha256": sha(ROOT / "backend/agent/nodes/fill.py")}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "rows": 27, "cells": 54,
                      "computed_routes": len(routes), "estimate_units": sorted(estimate_flows),
                      "fully_verified_rules": False,
                      "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
