"""Independent source-cell and task-dependent quantity-unit audit for mech 12-1-1."""
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

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/12-1-1.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p773-maintenance-12-1-1.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-12-1-1-panel-item-units-2026-10-19.json"

# Independently transcribed from the visible source rows on printed p.717.
EXPECTED = {
    "분전반 (W800×H500×D300이하)": ("대", "4.2", "2.8"),
    "조작반 (W800×H500×D300이하)": ("대", "4.2", "2.8"),
    "계기반(자립개방) (W1200×H2100×D800이하)": ("면", "6.72", "4.48"),
    "계기반(자립밀폐) (1200×2100×800)": ("면", "8.4", "5.6"),
    "계기반(현장) (900×900×600)": ("면", "5.88", "3.92"),
    "계기반(현장) (1000×1800×600)": ("면", "8.82", "5.88"),
    "계기반(현장) (1300×2000×700)": ("면", "9.88", "6.58"),
    "계기반(현장) (1400×2000×700)": ("면", "10.64", "7.09"),
    "계기반(발신기수납상) 1대용 (800×1600×900)": ("대", "2.0", "1.33"),
    "계기반(발신기수납상) 2대용 (1000×1600×900)": ("대", "2.4", "1.60"),
    "계기반(발신기수납상) 3대용 (1200×1600×900)": ("대", "2.8", "1.86"),
    "계기반(발신기수납상) 4대용 (1400×1600×900)": ("대", "3.2", "2.13"),
    "계기반(발신기수납상) 5대용 (1600×1600×900)": ("대", "3.6", "2.39"),
    "계기반(발신기수납상) 6대용 (1800×1600×900)": ("대", "4.0", "2.65"),
}
SOURCE_ROW_SIGNATURES = {
    "분전반 (W800×H500×D300이하)": "분전반 | 규격 W800×H500×D300이하 | 단위 대 | 계장공 4.2 | 보통인부 2.8",
    "조작반 (W800×H500×D300이하)": "조작반 | 규격 W800×H500×D300이하 | 단위 대 | 계장공 4.2 | 보통인부 2.8",
    "계기반(자립개방) (W1200×H2100×D800이하)": "계기반(자립개방) | 규격 W1200×H2100×D800이하 | 단위 면 | 계장공 6.72 | 보통인부 4.48",
    "계기반(자립밀폐) (1200×2100×800)": "계기반(자립밀폐) | 규격 1200×2100× 800 〃 | 단위 〃 | 계장공 8.4 | 보통인부 5.6",
    "계기반(현장) (900×900×600)": "계기반(현장) | 규격 900× 900× 600 〃 | 단위 〃 | 계장공 5.88 | 보통인부 3.92",
    "계기반(현장) (1000×1800×600)": "〃 | 규격 1000×1800× 600 〃 | 단위 〃 | 계장공 8.82 | 보통인부 5.88",
    "계기반(현장) (1300×2000×700)": "〃 | 규격 1300×2000× 700 〃 | 단위 〃 | 계장공 9.88 | 보통인부 6.58",
    "계기반(현장) (1400×2000×700)": "〃 | 규격 1400×2000× 700〃 | 단위 〃 | 계장공 10.64 | 보통인부 7.09",
    "계기반(발신기수납상) 1대용 (800×1600×900)": "〃(발신기수납상) | 규격 1대용W(800×1600×900) | 단위 대 | 계장공 2.0 | 보통인부 1.33",
    "계기반(발신기수납상) 2대용 (1000×1600×900)": "〃(〃) | 규격 2대용 (1000×1600×900) | 단위 〃 | 계장공 2.4 | 보통인부 1.60",
    "계기반(발신기수납상) 3대용 (1200×1600×900)": "〃(〃) | 규격 3대용 (1200×1600×900) | 단위 〃 | 계장공 2.8 | 보통인부 1.86",
    "계기반(발신기수납상) 4대용 (1400×1600×900)": "〃(〃) | 규격 4대용 (1400×1600×900) | 단위 〃 | 계장공 3.2 | 보통인부 2.13",
    "계기반(발신기수납상) 5대용 (1600×1600×900)": "〃(〃) | 규격 5대용 (1600×1600×900) | 단위 〃 | 계장공 3.6 | 보통인부 2.39",
    "계기반(발신기수납상) 6대용 (1800×1600×900)": "〃(〃) | 규격 6대용 (1800×1600×900) | 단위 〃 | 계장공 4.0 | 보통인부 2.65",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(table for table in spec["tables"] if table["id"] == "p773-t0")
    assert set(table["values"]) == set(EXPECTED)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    source_chunk = chunk_index["p773-t0"]["text"]
    doc = pymupdf.open(PDF_PATH)
    page_text = doc[772].get_text("text")
    assert "12-1-1" in page_text and "계기반 설치" in page_text and "W800" in page_text
    assert all(value in page_text for row in EXPECTED.values() for value in row[1:])

    cases = []
    for row, (unit, instrument, helper) in EXPECTED.items():
        assert table["values"][row] == {"단위": unit, "계장공": instrument, "보통인부": helper}, row
        # The PDF extractor retains ditto marks and splits name/spec into
        # columns while the spec uses expanded unique row labels. Compare the
        # complete original extracted source line, then independently compare
        # the rendered PDF table above; do not fuzzy-match the expanded label.
        signature = SOURCE_ROW_SIGNATURES[row]
        assert signature in source_chunk, (row, signature)
        for trade, value in (("계장공", instrument), ("보통인부", helper)):
            citation = cite_table("p773-t0", row, trade, value)
            assert citation.get("value") == value
        result = per_unit(spec, {"panel_item": row, "quantity": "1", "is_complete_product": True,
                                 "has_rear_panel": False, "test_adjustment": False})
        assert result.get("status") == "computed", (row, result)
        rates = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        assert rates == {"계장공": Fraction(instrument), "보통인부": Fraction(helper)}, (row, rates)
        assert result["unit_basis"]["per"] == f"1{unit}", (row, result["unit_basis"])
        cases.append({"item": row, "quantity_unit": unit,
                      "expected_rates": {"계장공": instrument, "보통인부": helper},
                      "computed_rates": {name: str(value) for name, value in rates.items()},
                      "status": "computed"})

    # The live estimate path asks the exact unit after the selected panel item.
    hit = {"rank": 1, "section_no": "12-1-1", "division": "기계설비",
           "section": f"12-1-1 {spec['title']}", "page": 717,
           "table_id": "p773-t0", "text": spec["title"], "chunk_id": "p773-t0"}
    def values(**items):
        return {name: {"value": value, "evidence": str(value)} for name, value in items.items()}
    spec_map = {("기계설비", "12-1-1"): [spec]}
    with patch.object(citation_runtime, "_pages",
                      return_value=defaultdict(lambda: {"printed_page": 717, "division": "기계설비"})), \
            patch.object(estimate_tools, "specs_by_section", return_value=spec_map), \
            patch.object(estimate_tools, "load_specs", return_value={spec["id"]: spec}), \
            patch.object(select_node, "specs_by_section", return_value=spec_map):
        session = estimate_tools.new_estimate("계기반 설치")
        estimate_tools.find_work(session, hits=[hit])
        first = estimate_tools.compute_labor(session)
        assert any(q["field"] == "panel_item" for q in first.get("missing", [])), first
        estimate_tools.set_conditions(session, "자립개방형 계기반", values=values(panel_item="계기반(자립개방) (W1200×H2100×D800이하)"), source="answer")
        asked = estimate_tools.compute_labor(session)
        quantity_question = next(q for q in asked.get("missing", []) if q["field"] == "quantity")
        assert quantity_question.get("unit") == "면", quantity_question
        estimate_tools.set_conditions(session, "2면", quantity={"value": "2", "unit": "면", "evidence": "2면"}, source="text")
        estimate_tools.set_conditions(session, "완제품이며 이면반 없음", values=values(
            is_complete_product=True, has_rear_panel=False, test_adjustment=False), source="answer")
        end_to_end = estimate_tools.compute_labor(session)
        assert end_to_end.get("status") == "ok", end_to_end
        flow_lines = {line["name"]: line for line in end_to_end["data"]["unit_lines"]}
        assert {name: Fraction(line["exact"]) for name, line in flow_lines.items()} == {
            "계장공": Fraction("6.72"), "보통인부": Fraction("4.48")}, flow_lines
        assert end_to_end["data"]["unit_basis"]["per"] == "1면"

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    audit = {
        "id": spec["id"], "status": "source_cells_and_all_task_dependent_units_verified",
        "source": {"physical_page": 773, "printed_page": 717,
                   "visual": "original PDF p.717 image visually checked; all 14 unit labels and 28 labor cells independently transcribed; each expanded spec row paired to its complete original extracted line, including ditto/spec continuation",
                   "pdf_sha256": sha(PDF_PATH), "image": str(IMAGE_PATH.relative_to(ROOT)),
                   "image_sha256": sha(IMAGE_PATH), "source_rows_checked": 14,
                   "labor_rate_cells_checked": 28, "rows": cases},
        "runtime": {"routes_computed": len(cases), "estimate_flow": {
            "selected_item": "계기반(자립개방) (W1200×H2100×D800이하)", "quantity_question_unit": "면",
            "status": end_to_end["status"], "unit_basis": end_to_end["data"]["unit_basis"]["per"],
            "unit_rates": {name: line["exact"] for name, line in flow_lines.items()}},
            "validation_issues": validation.get("issues", [])},
        "rule_scope": {"source_table_cells": "all 14 rows × unit + 2 labor rates; all 42 cells checked",
                       "citation_alias_note": "The source chunk keeps ditto-mark row labels while the spec expands them into unique canonical rows. Each route is paired by the exact source line signature and visually checked; strict row-substring validation does not crosswalk these canonical row labels.",
                       "source_notes": "Rear panel, unfinished-panel, and instrument test adjustments were outside this unit-route audit; no claim of full rule verification",
                       "all_rules_fully_verified": False},
        "spec_sha256": sha(SPEC_PATH), "runtime_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl")}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "rows": 14, "rate_cells": 28,
                      "computed_routes": len(cases), "estimate_quantity_unit": "면",
                      "fully_verified_rules": False, "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
