from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.nodes.compute import compute
from backend.agent.rules.specs import load_specs
from pipeline.validate_drafts import load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/기계설비/8-1-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CAPACITIES = ["10", "20", "30", "50", "80", "100", "150", "200", "300", "400", "500", "600"]
CONDITIONS = ["1회 지하1층", "1회 지하2층", "1회 지하3층", "2회 지하2층", "2회 지하3층", "소운반 10m 거리내", "가조립 설치기초상"]
TRADES = ["비계공", "특별인부"]
# Independent cell-by-cell transcription from the rendered original p.745.
ROWS = [
    ["3", "1", "3", "2", "3", "2", "6", "2", "7", "2", "1", "-", "2", "-"],
    ["4", "2", "4", "3", "5", "3", "7", "4", "10", "4", "2", "-", "3", "-"],
    ["5", "3", "5", "4", "7", "4", "10", "5", "12", "7", "2", "-", "4", "1"],
    ["7", "3", "7", "4", "9", "5", "14", "6", "16", "8", "2", "1", "4", "2"],
    ["10", "5", "12", "7", "15", "7", "23", "8", "28", "10", "4", "1", "7", "3"],
    ["14", "6", "16", "8", "20", "8", "30", "10", "36", "12", "4", "2", "7", "4"],
    ["20", "11", "24", "14", "31", "14", "46", "18", "57", "20", "6", "3", "13", "6"],
    ["29", "11", "32", "16", "40", "16", "60", "20", "72", "24", "7", "4", "16", "8"],
    ["40", "20", "44", "28", "56", "28", "80", "40", "90", "54", "12", "6", "24", "12"],
    ["50", "30", "56", "40", "72", "40", "100", "60", "112", "80", "16", "8", "34", "14"],
    ["60", "40", "70", "50", "90", "50", "120", "80", "140", "100", "20", "10", "40", "20"],
    ["70", "50", "84", "60", "108", "60", "140", "100", "169", "120", "24", "12", "48", "24"],
]
X_BOUNDS = [67.92, 118.56, 151.80, 179.40, 212.64, 240.24, 273.48, 301.08,
            334.32, 361.92, 395.16, 422.64, 456.00, 483.48, 516.72, 544.44]


def main() -> int:
    pkg = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = pkg["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p745-t0")
    assert spec["quantity_model"]["name"] == "per_unit"
    assert table["unit"] == "인/대"
    expected_values = {
        cap: {f"{condition} {trade}": ROWS[i][j]
              for j, (condition, trade) in enumerate((c, t) for c in CONDITIONS for t in TRADES)}
        for i, cap in enumerate(CAPACITIES)
    }
    assert table["values"] == expected_values

    # Reconstruct the original table's physical cells from the PDF word coordinates.
    with pymupdf.open(PDF) as document:
        page = document[744]
        cells: dict[tuple[int, int], str] = {}
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            if not (269.16 < y0 < 469.08 and 67.92 < x0 < 544.44):
                continue
            ri = round((y0 - 272.448) / 16.68)
            ci = next((i for i, (lo, hi) in enumerate(zip(X_BOUNDS, X_BOUNDS[1:]))
                       if lo <= (x0 + x1) / 2 < hi), None)
            if 0 <= ri < 12 and ci is not None:
                assert (ri, ci) not in cells, (ri, ci, cells.get((ri, ci)), word)
                cells[(ri, ci)] = word
        assert len(cells) == 12 * 15, (len(cells), sorted(set((r, c) for r in range(12) for c in range(15)) - cells.keys()))
        for ri, cap in enumerate(CAPACITIES):
            assert cells[(ri, 0)] == cap, (ri, cells[(ri, 0)], cap)
            for cj, expected in enumerate(ROWS[ri], start=1):
                assert cells[(ri, cj)] == expected, (cap, cj, cells[(ri, cj)], expected)

        note_text = "".join(page.get_text().split())
        assert all(note in note_text for note in ("현장반입후지하1층설치", "시운전품이포함", "기초및소운반은제외"))

    route_count = 0
    dash_count = 0
    for i, cap in enumerate(CAPACITIES):
        for ci, condition in enumerate(CONDITIONS):
            for ti, trade in enumerate(TRADES):
                expected = ROWS[i][ci * 2 + ti]
                quantity = "3"
                result = per_unit(spec, {"capacity": cap, "work_condition": condition,
                                         "quantity": quantity}, labor_only=True)
                assert result["status"] == "computed", (cap, condition, trade, result)
                line = next((x for x in result["unit_lines"] if x["name"] == trade), None)
                if expected == "-":
                    assert line is None, (cap, condition, trade, result)
                    excluded = next(x for x in result["provenance"]["excluded_resources"]
                                    if x["trade"] == trade)
                    assert excluded["citations"][0]["value"] == "-"
                    dash_count += 1
                else:
                    assert line is not None, (cap, condition, trade, result)
                    # per_unit returns the source rate per machine; the user quantity remains
                    # in the result context for the estimate/aggregation path.
                    assert Fraction(line["exact"]) == Fraction(expected), (cap, condition, trade, line)
                    cite = line["citations"][0]
                    assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                        "p745-t0", cap, f"{condition} {trade}", expected)
                route_count += 1

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    indexed = spec["id"] in load_specs()
    node_status = "not_registered"
    if indexed:
        node = compute({"spec_id": spec["id"], "inputs": {
            "capacity": "100", "work_condition": "1회 지하1층", "quantity": "3"}})
        assert node["status"] == "COMPUTED", node
        node_status = node["status"]
    report = {
        "id": spec["id"], "status": "pass", "source_page_physical": 745, "source_page_printed": 689,
        "independently_positioned_source_cells": len(cells), "source_numeric_cells": 163,
        "source_dash_cells": dash_count, "source_axes": {"capacities": 12, "conditions": 7, "trades": 2},
        "routes_checked": route_count, "quantity_cases": "all route pairs at quantity=3",
        "source_notes": {"after_delivery_install_floor_1": True, "test_run_included": True,
                         "foundation_and_short_haul_excluded": True},
        "basis_limitation": "Source table does not print an explicit 인/대 label; per-equipment basis is inferred from capacity rows and equipment infeed scope, so this audit is not full-rule verification.",
        "validator_ok": validation["ok"], "calculation_node": node_status,
        "full_rule_verification": False,
    }
    out = ROOT / "evals/runtime_validation/mechanical-8-1-1-refrigeration-infeed-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
