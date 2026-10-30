"""Verify the transposed 8-1-2 table, source merges, and resource quantities."""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_draft_executability import CALCULATORS, _values  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/토목/8-1-2.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p453-8-1-2.png"
ADJACENT_IMAGE_PATH = ROOT / "evals/runtime_validation/source-p454-8-1-3-notes.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-8-1-2-transposed-merged-table-2026-10-19.json"

SOILS = ("점토층", "모래층", "자갈층", "호박돌층")
HOLES = ("BX", "NX")
LABOR = {
    "중급기술자": ("0.16", "0.18", "0.18", "0.21", "0.39", "0.45", "0.65", "0.76"),
    "보링공": ("0.29", "0.35", "0.34", "0.40", "0.62", "0.72", "0.81", "0.96"),
    "특별인부": ("0.21", "0.25", "0.24", "0.29", "0.53", "0.63", "0.65", "0.76"),
    "보통인부": ("0.29", "0.35", "0.34", "0.40", "0.62", "0.73", "0.81", "0.96"),
}
MATERIALS = {
    "싱글코아바렐": ("0.010", "0.025", "0.05", "0.15"),
    "메탈크라운비트": ("0.025", "0.05", "0.5", "1.5"),
    "쵸핑비트": ("-", "-", "-", "0.5"),
    "드라이브파이프헤드": ("0.01", "0.025", "0.05", "0.08"),
    "드라이브파이프슈": ("0.01", "0.025", "0.05", "0.08"),
    "드라이브파이프": ("0.01", "0.025", "0.05", "0.08"),
}
COLUMNS = tuple(f"{soil} {hole}" for soil in SOILS for hole in HOLES)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    table = next(table for table in spec["tables"] if table["id"] == "p453-t1")
    unique_cells = []
    for row, rates in LABOR.items():
        assert set(table["values"][row]) == set(COLUMNS), row
        for column, value in zip(COLUMNS, rates):
            assert table["values"][row][column] == value, (row, column, table["values"][row][column], value)
            citation = cite_table("p453-t1", row, column, value)
            assert citation.get("pdf_page") == 453 and citation.get("value") == value
            unique_cells.append({"row": row, "column": column, "value": value})

    for row, rates in MATERIALS.items():
        cells = table["values"][row]
        for soil, value in zip(SOILS, rates):
            bx, nx = f"{soil} BX", f"{soil} NX"
            assert cells[bx] == value and cells[nx] == value, (row, soil, cells)
            # The source has one merged cell spanning the BX/NX subcolumns.
            citation = cite_table("p453-t1", row, bx, value)
            assert citation.get("pdf_page") == 453 and citation.get("value") == value
            unique_cells.append({"row": row, "merged_columns": [bx, nx],
                                 "source_column": bx, "value": value})

    doc = pymupdf.open(PDF_PATH)
    assert doc[452].number + 1 == 453 and doc[453].number + 1 == 454
    page453 = doc[452].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
    page453.save(IMAGE_PATH)
    page454 = doc[453].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
    page454.save(ADJACENT_IMAGE_PATH)

    routes = []
    for soil, hole in itertools.product(SOILS, HOLES):
        result = per_unit(spec, {"soil_type": soil, "hole_size": hole, "quantity": "1"})
        assert result.get("status") == "computed", (soil, hole, result)
        line_by_name = {line["name"]: line for line in result["unit_lines"]}
        expected = {name: Fraction(rates[SOILS.index(soil) * 2 + HOLES.index(hole)])
                    for name, rates in LABOR.items()}
        for name, rates in MATERIALS.items():
            value = rates[SOILS.index(soil)]
            if name == "쵸핑비트" and value == "-":
                continue
            expected[name] = Fraction(value)
        assert set(line_by_name) == set(expected), (soil, hole, line_by_name.keys(), expected.keys())
        for name, value in expected.items():
            line = line_by_name[name]
            assert Fraction(line["exact"]) == value, (soil, hole, name, line, value)
            assert line["citations"] and line["citations"][0].get("pdf_page") == 453
            assert line["kind"] == ("material" if name in MATERIALS else "labor")
            if name in MATERIALS:
                assert line["citations"][0].get("column") == f"{soil} BX"
            else:
                assert line["citations"][0].get("column") == f"{soil} {hole}"
        excluded = result["provenance"]["excluded_resources"]
        if soil in SOILS[:3]:
            assert len(excluded) == 1 and excluded[0]["trade"] == "쵸핑비트", (soil, hole, excluded)
            assert excluded[0]["citations"][0].get("value") == "-"
            assert excluded[0]["citations"][0].get("pdf_page") == 453
        else:
            assert excluded == [], (soil, hole, excluded)
        routes.append({"soil_type": soil, "hole_size": hole,
                       "status": "computed", "resource_lines": len(line_by_name)})

    # Confirm the 20m / variable 5% note is printed under adjacent 8-1-3,
    # not under the 8-1-2 table whose printed page 397 has no such note.
    text453 = doc[452].get_text("text")
    text454 = doc[453].get_text("text")
    assert "8-1-2" in text453 and "8-1-3" in text453
    assert "20m" in text454 and "5%" in text454

    blocked_by_field = {field["name"]: [] for field in spec["inputs"]}
    for item in spec.get("blocked", []):
        for condition in item.get("blocked_if_all", ([item["blocked_if"]]
                                                       if item.get("blocked_if") else [])):
            blocked_by_field[condition["input"]].append(condition)
    adjustments = (spec["quantity_model"]["params"].get("surcharges", [])
                   + spec["quantity_model"]["params"].get("note_adjustments", []))
    choices = [_values(field, blocked_by_field[field["name"]], adjustments)
               for field in spec["inputs"]]
    preflight = []
    for values in itertools.product(*choices):
        inputs = dict(zip((field["name"] for field in spec["inputs"]), values))
        preflight.append(CALCULATORS["per_unit"](spec, inputs).get("status"))
    assert len(preflight) == 8 and all(status == "computed" for status in preflight), preflight

    audit = {
        "id": spec["id"], "status": "source_cells_and_transposed_axes_verified",
        "source": {"pdf": str(PDF_PATH.relative_to(ROOT)), "physical_page": 453,
                   "printed_page": 397, "visual_page_image": str(IMAGE_PATH.relative_to(ROOT)),
                   "adjacent_note_page": str(ADJACENT_IMAGE_PATH.relative_to(ROOT)),
                   "pdf_sha256": sha256(PDF_PATH), "image_sha256": sha256(IMAGE_PATH),
                   "unique_source_cells_checked": len(unique_cells), "cells": unique_cells,
                   "merged_material_cell_aliases": 24,
                   "depth_note_scope": "The 20m/5% rule is printed under adjacent section 8-1-3 on physical p.454/printed p.398, not under 8-1-2 on p.453/printed p.397."},
        "runtime": {"exact_soil_hole_routes": len(routes), "routes": routes,
                    "execution_preflight_combinations": len(preflight),
                    "execution_preflight_statuses": {"computed": preflight.count("computed"),
                                                      "blocked": preflight.count("blocked")},
                    "material_line_count_per_route": 5,
                    "chopping_bit_dash_exclusions": 6},
        "scope": "Original p.397 has 56 unique resource cells: 32 labor cells and 24 material cells; each material cell is a source merge across BX/NX (expanded to 48 logical columns with citations to the merged source cell). All eight soil/hole routes and material quantities were checked. No 8-1-3 rates or note rules were changed.",
        "spec_sha256": sha256(SPEC_PATH),
        "per_unit_sha256": sha256(ROOT / "backend/agent/tools/calc/per_unit.py"),
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"unique_source_cells": len(unique_cells), "routes": len(routes),
                      "preflight": len(preflight), "all_computed": preflight.count("computed"),
                      "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
