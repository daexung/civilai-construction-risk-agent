"""Compare sparse source cells with p.679 and exercise both exact item routes."""
import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_draft_executability import CALCULATORS, _values
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.source.citation import cite_table

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE = ROOT / "evals/runtime_validation/source-p735-6-1-1.png"
AUDIT = ROOT / "evals/runtime_validation/per-unit-6-1-1-source-dashes-2026-10-19.json"
EXPECTED = {
    "ø13~15": ("0.148", "0.094"), "20~32": ("0.188", "0.113"),
    "40~50": ("0.253", "0.143"), "65~80": ("-", "0.446"),
    "100~125": ("-", "0.533"), "150~200": ("-", "0.686"),
    "250~300": ("-", "0.838"),
}
LABOR = ("배관공(인)", "보통인부(인)")
ITEMS = ("보호통", "유량계")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("*.json")
                if (lambda d: d.get("division") == "기계설비" and d.get("section_no") == "6-1-1")
                (json.loads(p.read_text(encoding="utf8"))["draft"]))
    spec = json.loads(path.read_text(encoding="utf8"))["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p735-t0")
    cells = []
    for size, (protection, meter) in EXPECTED.items():
        for item, value in zip(ITEMS, (protection, meter)):
            for trade in LABOR:
                column = f"{item} {trade}"
                actual = table["values"][size][column]
                assert actual == value, (size, column, actual, value)
                citation = cite_table("p735-t0", size, column, value)
                assert citation.get("value") == value and citation.get("pdf_page") == 735, citation
                cells.append({"row": size, "column": column, "value": value})
    doc = pymupdf.open(PDF)
    doc[734].get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8), alpha=False).save(IMAGE)
    source_text = doc[734].get_text("text")
    assert "65~80" in source_text and "0.446" in source_text
    routes = []
    for size, item in itertools.product(EXPECTED, ITEMS):
        result = per_unit(spec, {"meter_size": size, "install_item": item, "quantity": "1",
                                 "is_irregular_condition": False, "is_parallel_install": False})
        assert result.get("status") == "computed", (size, item, result)
        rate = EXPECTED[size][ITEMS.index(item)]
        if rate == "-":
            assert not result.get("unit_lines"), (size, item, result.get("unit_lines"))
            excluded = result["provenance"]["excluded_resources"]
            assert len(excluded) == 2 and {x["trade"] for x in excluded} == {"배관공", "보통인부"}
            assert all(x["citations"] and x["citations"][0].get("value") == "-" and x["citations"][0].get("pdf_page") == 735 for x in excluded), excluded
            routes.append({"size": size, "item": item, "status": "computed_with_two_source_dash_exclusions"})
        else:
            lines = {x["name"]: x for x in result["unit_lines"]}
            assert set(lines) == {"배관공", "보통인부"}
            assert all(Fraction(x["exact"]) == Fraction(rate) for x in lines.values())
            assert all(x["citations"][0].get("pdf_page") == 735 for x in lines.values())
            routes.append({"size": size, "item": item, "status": "computed", "labor_rate_each": rate})
    blocked_by_field = {field["name"]: [] for field in spec["inputs"]}
    for rule in spec.get("blocked", []):
        for condition in rule.get("blocked_if_all", ([rule["blocked_if"]] if rule.get("blocked_if") else [])):
            blocked_by_field[condition["input"]].append(condition)
    params = spec["quantity_model"]["params"]
    adjustments = params.get("surcharges", []) + params.get("note_adjustments", [])
    choices = [_values(field, blocked_by_field[field["name"]], adjustments) for field in spec["inputs"]]
    statuses = []
    for values in itertools.product(*choices):
        inputs = dict(zip((field["name"] for field in spec["inputs"]), values))
        statuses.append(CALCULATORS["per_unit"](spec, inputs).get("status"))
    assert len(statuses) == 56 and set(statuses) == {"computed"}, {"n": len(statuses), "statuses": sorted(set(statuses))}
    audit = {"id": spec["id"], "status": "source_sparse_cells_verified", "source": {
        "physical_page": 735, "printed_page": 679, "visual_image": str(IMAGE.relative_to(ROOT)),
        "pdf_sha256": sha(PDF), "image_sha256": sha(IMAGE), "unique_cells_checked": len(cells), "cells": cells,
        "reading": "Printed p.679 has explicit dashes in both protection labor columns for 65~80, 100~125, 150~200, and 250~300; these cells are source exclusions, not zero rates or missing selectors."},
        "runtime": {"exact_size_item_routes": len(routes), "routes": routes,
                    "execution_preflight_combinations": len(statuses),
                    "execution_preflight_statuses": {"computed": statuses.count("computed"), "blocked": statuses.count("blocked")}},
        "scope": "28 unique original cells and 14 exact size/item routes checked. Irregular-condition and parallel-install adjustments were not independently audited in this targeted source-cell pass.",
        "spec_sha256": sha(path), "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"cells": len(cells), "routes": len(routes), "audit": str(AUDIT.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
