"""Source-cell and exact-route check for civil drilling section 8-1-3."""
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

SPEC_PATH = ROOT / "data/drafts/specs/토목/8-1-3.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p454-8-1-3.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-8-1-3-transposed-continuation-2026-10-19.json"

ROCKS = ("풍화암", "연암", "보통암", "경암", "극경암")
HOLES = ("BX", "NX")
LABOR = {
    "중급기술자": ("0.16", "0.19", "0.17", "0.21", "0.17", "0.20", "0.33", "0.39", "0.37", "0.43"),
    "보링공": ("0.30", "0.35", "0.31", "0.37", "0.40", "0.47", "0.53", "0.62", "0.63", "0.75"),
    "특별인부": ("0.22", "0.26", "0.24", "0.28", "0.20", "0.24", "0.44", "0.51", "0.47", "0.56"),
    "보통인부": ("0.30", "0.35", "0.31", "0.37", "0.40", "0.47", "0.53", "0.62", "0.63", "0.75"),
}
MATERIALS = {
    "더블코아바렐": ("0.02", "0.025", "0.025", "0.04", "0.05"),
    "메탈크라운비트": ("0.8", "1.0", "1.0", "-", "-"),
    "다이아몬드비트": ("-", "-", "-", "0.1", "0.12"),
    "메탈리밍쉘": ("0.02", "0.025", "0.025", "-", "-"),
    "다이아몬드리밍쉘": ("-", "-", "-", "0.03", "0.04"),
    "코아리프터": ("0.1", "0.1", "0.1", "0.1", "0.1"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    cells = []
    for table_id, rows in (("p453-t2", LABOR), ("p454-t0", LABOR)):
        table = tables[table_id]
        selected = ({k: v for k, v in rows.items() if k in ("중급기술자", "보링공")}
                    if table_id == "p453-t2" else
                    {k: v for k, v in rows.items() if k in ("특별인부", "보통인부")})
        for row, rates in selected.items():
            for col, value in zip((f"{r} {h}" for r in ROCKS for h in HOLES), rates):
                assert table["values"][row][col] == value, (table_id, row, col)
                cite = cite_table(table_id, row, col, value)
                assert cite.get("value") == value and cite.get("pdf_page") == (453 if table_id == "p453-t2" else 454), cite
                cells.append({"table": table_id, "row": row, "column": col, "value": value})
    for row, rates in MATERIALS.items():
        for rock, value in zip(ROCKS, rates):
            table = tables["p454-t0"]["values"][row]
            assert table[f"{rock} BX"] == value and table[f"{rock} NX"] == value, (row, rock)
            cite = cite_table("p454-t0", row, f"{rock} BX", value)
            assert cite.get("value") == value and cite.get("pdf_page") == 454, cite
            cells.append({"table": "p454-t0", "row": row, "merged_columns": [f"{rock} BX", f"{rock} NX"], "source_column": f"{rock} BX", "value": value})
    assert len(cells) == 70, len(cells)

    doc = pymupdf.open(PDF_PATH)
    pix = doc[453].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
    pix.save(IMAGE_PATH)
    text = doc[453].get_text("text")
    assert "20m" in text and "5%" in text

    routes = []
    for rock, hole in itertools.product(ROCKS, HOLES):
        inp = {"rock_type": rock, "hole_size": hole, "quantity": "1", "depth": "20", "is_inclined": False, "is_over_water": False}
        result = per_unit(spec, inp)
        assert result.get("status") == "computed", (inp, result)
        actual = {line["name"]: line for line in result["unit_lines"]}
        expected = {name: Fraction(values[ROCKS.index(rock)*2 + HOLES.index(hole)]) for name, values in LABOR.items()}
        for name, values in MATERIALS.items():
            if values[ROCKS.index(rock)] != "-":
                expected[name] = Fraction(values[ROCKS.index(rock)])
        assert set(actual) == set(expected), (inp, actual.keys(), expected.keys())
        for name, value in expected.items():
            line = actual[name]
            assert Fraction(line["exact"]) == value, (inp, name, line, value)
            assert line["citations"] and line["citations"][0].get("pdf_page") in (453, 454)
            if name in MATERIALS:
                assert line["citations"][0].get("column") == f"{rock} BX"
        excluded = result["provenance"]["excluded_resources"]
        dash_rows = [name for name, vals in MATERIALS.items() if vals[ROCKS.index(rock)] == "-"]
        assert {x["trade"] for x in excluded} == set(dash_rows), (inp, excluded, dash_rows)
        assert all(x["citations"][0].get("value") == "-" and x["citations"][0].get("pdf_page") == 454 for x in excluded)
        routes.append({"rock_type": rock, "hole_size": hole, "status": "computed", "line_count": len(actual), "excluded_dash_rows": dash_rows})

    for inp in (
        {"rock_type": "풍화암", "hole_size": "BX", "quantity": "1", "depth": "21", "is_inclined": False, "is_over_water": False},
        {"rock_type": "풍화암", "hole_size": "BX", "quantity": "1", "depth": "20", "is_inclined": True, "is_over_water": False},
    ):
        result = per_unit(spec, inp)
        assert result.get("status") == "blocked", (inp, result)
        routes.append({"rock_type": inp["rock_type"], "hole_size": inp["hole_size"], "depth": inp["depth"], "is_inclined": inp["is_inclined"], "status": "blocked_with_source_policy"})

    blocked_by_field = {f["name"]: [] for f in spec["inputs"]}
    for item in spec.get("blocked", []):
        for c in item.get("blocked_if_all", ([item["blocked_if"]] if item.get("blocked_if") else [])):
            blocked_by_field[c["input"]].append(c)
    adjustments = spec["quantity_model"]["params"].get("surcharges", []) + spec["quantity_model"]["params"].get("note_adjustments", [])
    choices = [_values(f, blocked_by_field[f["name"]], adjustments) for f in spec["inputs"]]
    statuses = []
    for vals in itertools.product(*choices):
        inp = dict(zip((f["name"] for f in spec["inputs"]), vals))
        statuses.append(CALCULATORS["per_unit"](spec, inp).get("status"))
    assert statuses and set(statuses) <= {"computed", "blocked"} and "computed" in statuses, {"n": len(statuses), "counts": {s: statuses.count(s) for s in set(statuses)}}
    audit = {"id": spec["id"], "status": "source_cells_and_continuation_axes_verified", "source": {"pdf": str(PDF_PATH.relative_to(ROOT)), "physical_pages": [453, 454], "printed_pages": [397, 398], "visual_page_image": str(IMAGE_PATH.relative_to(ROOT)), "pdf_sha256": sha(PDF_PATH), "image_sha256": sha(IMAGE_PATH), "unique_source_cells_checked": len(cells), "cells": cells, "material_aliases_for_merged_cells": 30}, "runtime": {"exact_rock_hole_routes": 10, "routes": routes, "preflight_combinations": len(statuses), "preflight_statuses": {s: statuses.count(s) for s in sorted(set(statuses))}, "open_policies": ["depth over 20m: source says add 5% every 10m within a range; no selected rate", "inclined drilling: rod raising and slime removal are separately accounted; no added amount selected", "over-water separately accounted cost remains outside this rate"]}, "scope": "70 distinct original cells (40 labor, 30 material; material values are merged BX/NX cells). Ten exact rock/hole routes and source dashes were checked. Depth>20 and inclined rules remain blocked and are not treated as resolved.", "spec_sha256": sha(SPEC_PATH), "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_cells": len(cells), "routes": len(routes), "preflight": len(statuses), "preflight_statuses": audit["runtime"]["preflight_statuses"], "audit": str(AUDIT_PATH.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
