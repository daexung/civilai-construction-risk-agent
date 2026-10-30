"""Independently compare and exercise all explicit 13-3-1 base matrices."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.estimate import tools as estimate_tools
from backend.agent.nodes import select as select_node
from backend.agent.nodes.fill import extract_inputs
from backend.agent.tools.source import citation as citation_runtime
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/13-3-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
OUT = ROOT / "evals/runtime_validation/per-unit-13-3-1-insulation-tables-2026-10-19.json"
THICKNESSES = ["30mm이하", "31~40mm", "41~60mm", "61~75mm", "76~90mm"]
TARGETS = {"관": "m", "Fitting": "개", "Hanger": "개", "Valve및Flange": "개"}
LABOR_COLUMNS = {
    "관": ["관(m당) 보온공", "관(m당) 특별인부"],
    "Fitting": ["Fitting(개당) 보온공", "Fitting(개당) 특별인부"],
    "Hanger": ["Hanger(개당) 보온공", "Hanger(개당) 특별인부"],
    "Valve및Flange": ["Valve및Flange(개당) 보온공", "Valve및Flange(개당) 특별인부"],
}
MATERIAL_COLUMNS = {
    "성형물": ("직관의물량 성형물(m)", "m"),
    "철선": ("직관의물량 철선(m)", "m"),
    "Lagging Sheet": ("직관의물량 Lagging Sheet(㎡)", "㎡"),
    "Sheet Metal Screw": ("직관의물량 Sheet Metal Screw(개)", "개"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_matrix(page_no: int) -> dict[str, dict[str, str]]:
    grid = pymupdf.open(PDF)[page_no - 1].find_tables().tables[0].extract()
    labels = [" ".join(x.split()) for x in (grid[2][0] or "").splitlines() if x.strip()]
    headers = [
        "관(m당) 보온공", "관(m당) 특별인부",
        "Fitting(개당) 보온공", "Fitting(개당) 특별인부",
        "Hanger(개당) 보온공", "Hanger(개당) 특별인부",
        "Valve및Flange(개당) 보온공", "Valve및Flange(개당) 특별인부",
        "직관의물량 성형물(m)", "직관의물량 철선(m)",
        "직관의물량 Lagging Sheet(㎡)", "직관의물량 Sheet Metal Screw(개)",
    ]
    assert len(headers) == 12 and len(labels) == 17, (page_no, headers, labels)
    cols = [[" ".join(x.split()) for x in (grid[2][j] or "").splitlines() if x.strip()]
            for j in range(1, 13)]
    assert all(len(col) == len(labels) for col in cols), (page_no, [len(c) for c in cols])
    return {row: dict(zip(headers, (col[i] for col in cols))) for i, row in enumerate(labels)}


def compute(draft: dict, args: dict) -> dict:
    return per_unit(draft, args)


def live_estimate(draft: dict, target: str) -> dict:
    page = 813
    hit = {"rank": 1, "section_no": "13-3-1", "division": "기계설비",
           "section": draft["title"], "page": page, "table_id": "p813-t0",
           "chunk_id": "p813-t0", "text": draft["title"]}
    sections = {("기계설비", "13-3-1"): [draft]}
    with patch.object(citation_runtime, "_pages", return_value=defaultdict(
            lambda: {"printed_page": 757, "division": "기계설비"})), \
         patch.object(estimate_tools, "specs_by_section", return_value=sections), \
         patch.object(estimate_tools, "load_specs", return_value={draft["id"]: draft}), \
         patch.object(select_node, "specs_by_section", return_value=sections):
        state = estimate_tools.new_estimate("pipe 보온")
        estimate_tools.find_work(state, hits=[hit])
        estimate_tools.compute_labor(state)
        values = {"insulation_thickness": "30mm이하", "pipe_size": "50이하",
                  "target_type": target, "lagging_material": "해당없음",
                  "overlap_count": 1, "temperature_type": "Hot"}
        first_set = estimate_tools.set_conditions(state, "원문 조건 확인", values={
            k: {"value": v, "evidence": str(v)} for k, v in values.items()}, source="answer")
        missing = estimate_tools.compute_labor(state)
        quantity = next(x for x in missing.get("missing", []) if x["field"] == "quantity")
        assert quantity.get("unit") == TARGETS[target], quantity
        second_set = estimate_tools.set_conditions(state, f"물량 2{TARGETS[target]}", quantity={
            "value": "2", "unit": TARGETS[target], "evidence": f"2{TARGETS[target]}"}, source="text")
        result = estimate_tools.compute_labor(state)
        assert result.get("status") == "ok", {"first_set": first_set, "second_set": second_set, "result": result}
        return {"target_type": target, "prompt_unit": quantity["unit"], "status": result["status"]}


def main() -> None:
    import os
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC.read_text(encoding="utf-8")); draft = package["draft"]
    tables = {t["id"]: t for t in draft["tables"]}
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_index = chunks_by_id_from_list(chunks)
    source = {f"p{page}-t0": source_matrix(page) for page in range(813, 818)}
    source_cells = numeric_cells = 0
    for page, thickness in zip(range(813, 818), THICKNESSES):
        table_id = f"p{page}-t0"; actual = tables[table_id]["values"]
        assert {k: v for k, v in actual.items() if k != "비고"} == source[table_id], table_id
        assert len(chunk_index[table_id].get("text", "")) > 100
        assert chunk_index[table_id].get("source", {}).get("page") == page
        for row, columns in source[table_id].items():
            for column, raw in columns.items():
                assert check_table_citation(chunk_index, {"table_id": table_id, "row": row,
                                                          "column": column, "value": raw}) is None, (table_id, row, column, raw)
                Fraction(raw)
                source_cells += 1; numeric_cells += 1
        assert tables[table_id]["role"] == f"보온두께 {thickness} 품"
    assert source_cells == 1020 and numeric_cells == 1020
    parsed, ambiguities = extract_inputs(
        "보온두께 30mm이하 파이프 50이하 관 2m 해당없음 Hot 1회", draft)
    assert not ambiguities and parsed.get("target_type") == "관" and parsed.get("quantity") == "2", (parsed, ambiguities)

    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    assert rate["table_selector"]["values"] == dict(zip(THICKNESSES, source))
    assert rate["row_value_map"] == {"50이하": "φ 50이하"}
    labor_routes = material_routes = surcharge_cases = 0
    for thickness, table_id in zip(THICKNESSES, source):
        for row, cells in source[table_id].items():
            size = "50이하" if row.startswith("φ") else row
            for target, unit in TARGETS.items():
                for lagging, adjustment in (("해당없음", Fraction(0)),
                                             ("Prefabricated Sheet", Fraction(1, 2)),
                                             ("원자재", Fraction(1))):
                    args = {"insulation_thickness": thickness, "pipe_size": size,
                            "target_type": target, "quantity": "2",
                            "lagging_material": lagging, "overlap_count": 1,
                            "temperature_type": "Hot"}
                    result = compute(draft, args)
                    assert result.get("status") == "computed", (args, result)
                    lines = {line["name"]: line for line in result["unit_lines"]}
                    for trade, column in zip(("보온공", "특별인부"), LABOR_COLUMNS[target]):
                        expected = Fraction(cells[column]) * (1 + adjustment)
                        line = lines[trade]
                        assert Fraction(line["exact"]) == expected, (args, trade, line, expected)
                        cite = line["citations"][0]
                        assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (table_id, row, column, cells[column])
                        if adjustment:
                            note_cites = [entry for entry in line["citations"]
                                          if entry.get("internal_id") == "p813-t0"
                                          and entry.get("row") == "비고" and entry.get("column") == "비고"]
                            assert len(note_cites) == 1 and ("50%" if adjustment == Fraction(1, 2) else "100%") in note_cites[0]["value"]
                        labor_routes += 1
                    material_lines = {line["name"]: line for line in result["unit_lines"] if line["kind"] == "material"}
                    if target == "관":
                        assert set(material_lines) == set(MATERIAL_COLUMNS), (args, material_lines.keys())
                        for name, (column, material_unit) in MATERIAL_COLUMNS.items():
                            expected = Fraction(cells[column])
                            line = material_lines[name]
                            assert Fraction(line["exact"]) == expected, (args, name, line, expected)
                            assert line["unit"] == f"{material_unit}/m"
                            citation = line["citations"][0]
                            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (table_id, row, column, cells[column])
                            material_routes += 1
                    else:
                        assert not material_lines, (args, material_lines)
                    surcharge_cases += 1

    blocked = []
    for args in (
        {"insulation_thickness": "91mm이상", "pipe_size": "50이하", "target_type": "관", "quantity": "1", "lagging_material": "해당없음", "overlap_count": 1, "temperature_type": "Hot"},
        {"insulation_thickness": "30mm이하", "pipe_size": "50이하", "target_type": "관", "quantity": "1", "lagging_material": "해당없음", "overlap_count": 1, "temperature_type": "Cold"},
        {"insulation_thickness": "30mm이하", "pipe_size": "50이하", "target_type": "관", "quantity": "1", "lagging_material": "Prefabricated Sheet", "overlap_count": 2, "temperature_type": "Hot"},
    ):
        result = compute(draft, args); assert result.get("status") == "blocked", (args, result)
        blocked.append({"conditions": {k: v for k, v in args.items() if k != "quantity"}, "reason": result.get("reason")})

    validation = validate_one(SPEC, ROOT / "data/drafts/specs", chunk_index, None)
    assert not validation.get("issues"), validation
    flows = [live_estimate(draft, "관"), live_estimate(draft, "Fitting")]
    report = {
        "id": draft["id"], "status": "source_matrices_units_surcharges_and_materials_verified",
        "source": {"physical_pages": list(range(813, 818)), "printed_pages": list(range(757, 762)),
                   "source_tables": list(source), "rows_per_table": 17, "cells_checked": source_cells,
                   "cell_value_source": "Independent PyMuPDF extraction from the saved original PDF; exact table coordinates also checked against existing citation chunks."},
        "runtime": {"unit_rate_routes": labor_routes, "additional_material_routes": material_routes,
                    "target_unit_routes": TARGETS, "source_surcharge_cases": surcharge_cases,
                    "live_estimate_flows": flows, "blocked_source_policies": blocked},
        "rule_scope": {"all five explicit table thicknesses and all row/target/trade rates verified": True,
                       "four direct-pipe material quantities verified": True,
                       "91mm+ formula, Cold qualitative surcharge, and multi-layer combination remain blocked": True,
                       "all_rules_fully_verified": False},
        "hashes": {"spec_sha256": sha(SPEC), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
                   "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
                   "runtime_fill_sha256": sha(ROOT / "backend/agent/nodes/fill.py")},
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "source_cells": source_cells,
                      "labor_routes": labor_routes, "material_routes": material_routes,
                      "surcharge_cases": surcharge_cases, "live_flows": flows,
                      "fully_verified_rules": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
