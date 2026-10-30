"""Recover five exact pipe-insulation matrices from the saved original PDF."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-3-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
BACKUP = ROOT / "evals/runtime_validation/13-3-1-pre-restoration-spec-2026-10-19.json"
THICKNESSES = ["30mm이하", "31~40mm", "41~60mm", "61~75mm", "76~90mm"]
HEADER = [
    "관(m당) 보온공", "관(m당) 특별인부",
    "Fitting(개당) 보온공", "Fitting(개당) 특별인부",
    "Hanger(개당) 보온공", "Hanger(개당) 특별인부",
    "Valve및Flange(개당) 보온공", "Valve및Flange(개당) 특별인부",
    "직관의물량 성형물(m)", "직관의물량 철선(m)",
    "직관의물량 Lagging Sheet(㎡)", "직관의물량 Sheet Metal Screw(개)",
]
TABLE_IDS = [f"p{page}-t0" for page in range(813, 818)]


def split_cell(value: object) -> list[str]:
    return [" ".join(line.split()) for line in str(value or "").splitlines() if line.strip()]


def read_source(doc: pymupdf.Document, page_no: int) -> dict[str, dict[str, str]]:
    tables = doc[page_no - 1].find_tables().tables
    assert len(tables) == 1, (page_no, len(tables))
    grid = tables[0].extract()
    assert len(grid) == 4 and len(grid[0]) == 13, (page_no, len(grid), [len(row) for row in grid])
    assert [" ".join(str(x or "").split()) for x in grid[0]][1:9:2] == ["관(m당)", "Fitting(개당)", "Hanger(개당)", "Valve및Flange(개당)"], page_no
    rows = split_cell(grid[2][0])
    columns = [split_cell(grid[2][i]) for i in range(1, 13)]
    assert len(rows) == 17 and all(len(values) == 17 for values in columns), (page_no, len(rows), [len(v) for v in columns])
    result = {}
    for index, row in enumerate(rows):
        assert row not in result, (page_no, row)
        result[row] = {name: values[index] for name, values in zip(HEADER, columns)}
    return result


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old = {table["id"]: table for table in draft["tables"]}
    backup_package = json.loads(BACKUP.read_text(encoding="utf-8"))
    backup_tables = {table["id"]: table for table in backup_package["draft"]["tables"]}
    note = backup_tables["p813-t0"]["values"].get("비고")
    doc = pymupdf.open(PDF)
    recovered = []
    for page, table_id, thickness in zip(range(813, 818), TABLE_IDS, THICKNESSES):
        values = read_source(doc, page)
        table = old.get(table_id, {
            "id": table_id,
            "role": f"보온두께 {thickness} 품",
            "source": f"PDF {page}쪽 {thickness} 표",
            "unit": None,
            "cite": {"table_id": table_id},
        })
        table["role"] = f"보온두께 {thickness} 품"
        table["source"] = f"PDF {page}쪽 {thickness} 표"
        table["unit"] = None
        table["cite"] = {"table_id": table_id}
        table["values"] = values
        recovered.append(table)
    # The note is a source rule rather than a rate row. Keep its literal citation
    # in the first table for the existing blocked-policy reference.
    if note:
        recovered[0]["values"]["비고"] = note
    draft["tables"] = recovered + [table for table in draft["tables"] if table["id"] not in TABLE_IDS]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate.update({
        "table": TABLE_IDS[0],
        "table_selector": {"input": "insulation_thickness", "values": dict(zip(THICKNESSES, TABLE_IDS))},
        "row_value_map": {"50이하": "φ 50이하"},
        "quantity_unit_selector": {"input": "target_type", "values": {"관": "m", "Fitting": "개", "Hanger": "개", "Valve및Flange": "개"}},
    })
    source_note = note["비고"]
    assert "Prefabricated Sheet로 Lagging할 때는 본 품에 50%를 가산한다" in source_note
    assert "원자재 (Rawmaterial)로 시공할 때는 본 품에 100%를 가산한다" in source_note
    params = draft["quantity_model"]["params"]
    params["surcharges"] = []
    rate["base_rate_multipliers"] = [
        {"when": {"lagging_material": "Prefabricated Sheet"}, "factor": "1.5",
         "cite": {"table_id": "p813-t0", "row": "비고", "column": "비고", "value": source_note}},
        {"when": {"lagging_material": "원자재"}, "factor": "2",
         "cite": {"table_id": "p813-t0", "row": "비고", "column": "비고", "value": source_note}},
    ]
    quantity_field = next(field for field in draft["inputs"] if field["name"] == "quantity")
    quantity_field["unit_by"] = {"input": "target_type", "values": {"관": "m", "Fitting": "개", "Hanger": "개", "Valve및Flange": "개"}}
    materials = []
    material_columns = [
        ("성형물", "직관의물량 성형물(m)", "m"),
        ("철선", "직관의물량 철선(m)", "m"),
        ("Lagging Sheet", "직관의물량 Lagging Sheet(㎡)", "㎡"),
        ("Sheet Metal Screw", "직관의물량 Sheet Metal Screw(개)", "개"),
    ]
    for thickness, table_id in zip(THICKNESSES, TABLE_IDS):
        for name, column, unit in material_columns:
            materials.append({
                "name": name, "table": table_id,
                "row_selector": {"input": "pipe_size", "contains": ["{value}"],
                                 "exact_component_inputs": ["pipe_size"],
                                 "value_map": {"50이하": "φ 50이하"}},
                "column": column, "unit": unit, "basis": "m",
                "quantity_input": "quantity", "quantity_unit": "m",
                "when": {"target_type": "관", "insulation_thickness": thickness},
                "source": f"{table_id} 직관의 물량 열",
            })
    draft["quantity_model"]["params"]["additional_materials"] = materials
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tables": len(TABLE_IDS), "rows_per_table": 17, "source_rate_and_material_cells": len(TABLE_IDS) * 17 * 12, "note_row_retained": bool(note), "additional_material_routes": len(materials)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
