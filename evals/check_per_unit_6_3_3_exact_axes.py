"""Compare every 6-3-3 source cell with the PDF and exercise exact axes offline."""
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

SPEC_PATH = ROOT / "data/drafts/specs/토목/6-3-3.json"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE_PATH = ROOT / "evals/runtime_validation/source-p424-6-3-3.png"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-6-3-3-exact-coating-axes-2026-10-19.json"

EXPECTED = {
    "300": ("-", "-", "0.18", "0.04"),
    "350": ("-", "-", "0.21", "0.05"),
    "400": ("-", "-", "0.23", "0.06"),
    "450": ("-", "-", "0.25", "0.06"),
    "500": ("-", "-", "0.27", "0.07"),
    "600": ("-", "-", "0.30", "0.07"),
    "700": ("-", "-", "0.32", "0.08"),
    "800": ("0.27", "0.07", "0.34", "0.08"),
    "900": ("0.28", "0.07", "0.36", "0.09"),
    "1,000": ("0.30", "0.07", "0.38", "0.09"),
    "1,100": ("0.31", "0.08", "0.40", "0.10"),
    "1,200": ("0.32", "0.08", "0.41", "0.10"),
    "1,350": ("0.33", "0.08", "0.43", "0.11"),
    "1,500": ("0.35", "0.09", "0.45", "0.11"),
    "1.650": ("0.36", "0.09", "0.46", "0.11"),
    "1,800": ("0.37", "0.09", "0.48", "0.12"),
    "2,000": ("0.39", "0.09", "0.49", "0.12"),
    "2,200": ("0.40", "0.10", "0.51", "0.13"),
    "2,400": ("0.41", "0.10", "0.53", "0.13"),
}
COLUMNS = (
    "내부도장 도장공(인)", "내부도장 보통인부(인)",
    "외부도장 도장공(인)", "외부도장 보통인부(인)",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    table = next(table for table in spec["tables"] if table["id"] == "p424-t0")
    assert set(table["values"]) == set(EXPECTED)
    cells = []
    for row, values in EXPECTED.items():
        row_cells = table["values"][row]
        assert set(row_cells) == set(COLUMNS), (row, row_cells)
        for column, value in zip(COLUMNS, values):
            assert str(row_cells[column]) == value, (row, column, row_cells[column], value)
            citation = cite_table("p424-t0", row, column, value)
            assert citation.get("pdf_page") == 424 and citation.get("value") == value
            cells.append({"row": row, "column": column, "value": value,
                          "pdf_page": 424, "printed_page": 368})

    document = pymupdf.open(PDF_PATH)
    assert document[423].number + 1 == 424
    pix = document[423].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
    pix.save(IMAGE_PATH)

    computed, blocked, routes = 0, 0, []
    for row, values in EXPECTED.items():
        for coating, start in (("내부도장", 0), ("외부도장", 2)):
            result = per_unit(spec, {"pipe_diameter": row, "coating_type": coating, "quantity": "1"})
            source_rates = values[start:start + 2]
            if coating == "내부도장" and source_rates == ("-", "-"):
                assert result.get("status") == "blocked", (row, coating, result)
                assert len(result.get("citations", [])) == 2, (row, result)
                assert all(citation.get("value") == "-" and citation.get("pdf_page") == 424
                           for citation in result["citations"]), result
                blocked += 1
                routes.append({"diameter": row, "coating_type": coating,
                               "status": "blocked_by_two_source_dashes"})
                continue
            assert result.get("status") == "computed", (row, coating, result)
            expected_rates = {
                "도장공(인)": Fraction(source_rates[0]),
                "보통인부(인)": Fraction(source_rates[1]),
            }
            actual = {line["name"]: Fraction(line["exact"])
                      for line in result["unit_lines"]}
            assert actual == expected_rates, (row, coating, expected_rates, actual)
            for line in result["unit_lines"]:
                assert len(line["citations"]) == 1
                citation = line["citations"][0]
                assert citation.get("pdf_page") == 424 and citation.get("row") == row
                assert citation.get("value") == str(source_rates[
                    0 if line["name"] == "도장공(인)" else 1])
            computed += 1
            routes.append({"diameter": row, "coating_type": coating, "status": "computed",
                           "rates": {name: str(value) for name, value in expected_rates.items()}})

    blocked_by_field = {field["name"]: [] for field in spec["inputs"]}
    for item in spec.get("blocked", []):
        conditions = item.get("blocked_if_all", [])
        if item.get("blocked_if"):
            conditions = [item["blocked_if"]]
        for condition in conditions:
            blocked_by_field[condition["input"]].append(condition)
    adjustments = (spec["quantity_model"]["params"].get("surcharges", [])
                   + spec["quantity_model"]["params"].get("note_adjustments", []))
    choices = [_values(field, blocked_by_field[field["name"]], adjustments)
               for field in spec["inputs"]]
    runner_statuses = []
    for values in itertools.product(*choices):
        inputs = dict(zip((field["name"] for field in spec["inputs"]), values))
        result = CALCULATORS["per_unit"](spec, inputs)
        runner_statuses.append(result.get("status"))
    assert runner_statuses and runner_statuses[0] == "computed", runner_statuses
    assert all(status in ("computed", "blocked") for status in runner_statuses), runner_statuses

    audit = {
        "id": spec["id"], "status": "source_cell_and_exact_axis_verified",
        "source": {"pdf": str(PDF_PATH.relative_to(ROOT)), "physical_page": 424,
                   "printed_page": 368, "visual_page_image": str(IMAGE_PATH.relative_to(ROOT)),
                   "pdf_sha256": sha256(PDF_PATH), "image_sha256": sha256(IMAGE_PATH),
                   "independent_cells_checked": len(cells), "cells": cells},
        "runtime": {"routes_checked": len(routes), "computed_routes": computed,
                    "dash_blocked_routes": blocked, "routes": routes,
                    "execution_preflight_combinations": len(runner_statuses),
                    "execution_preflight_statuses": {
                        "computed": runner_statuses.count("computed"),
                        "blocked": runner_statuses.count("blocked")}},
        "scope": "All 19 diameters and all four coating/trade columns (76 cells) were checked against original PDF p.424 and independently compared to per_unit output. Internal coating remains source-blocked where the original cells are dashes. This does not verify costs or unrelated work sections.",
        "spec_sha256": sha256(SPEC_PATH),
        "per_unit_sha256": sha256(ROOT / "backend/agent/tools/calc/per_unit.py"),
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cells": len(cells), "routes": len(routes), "computed": computed,
                      "source_dash_blocked": blocked, "audit": str(AUDIT_PATH.relative_to(ROOT))},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
