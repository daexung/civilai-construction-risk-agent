"""Verify the 9-3-2 two-page source grid and exact diameter/thickness/site routing."""
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
IMAGES = [ROOT / "evals/runtime_validation/source-p759-9-3-2.png", ROOT / "evals/runtime_validation/source-p760-9-3-2.png"]
AUDIT = ROOT / "evals/runtime_validation/per-unit-9-3-2-exact-structure-axes-2026-10-19.json"
EXPECTED = {
    "25": ("0.096", "0.123", "0.169", "0.216"),
    "50": ("0.119", "0.152", "0.208", "0.266"),
    "75": ("0.142", "0.181", "0.248", "0.317"),
    "100": ("0.165", "0.211", "0.287", "0.368"),
    "150": ("0.210", "0.268", "0.367", "0.469"),
    "200": ("0.252", "0.322", "0.446", "0.570"),
    "250": ("0.295", "0.377", "0.525", "0.671"),
    "300": ("0.339", "0.434", "0.604", "0.772"),
    "350": ("0.384", "0.491", "0.683", "0.874"),
    "400": ("0.426", "0.544", "0.762", "0.975"),
}
THICKNESS = ("150mm", "300mm")
SITES = ("바닥", "벽체")
TRADES = ("착암공", "보통인부")

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    path = next(p for p in (ROOT / "data/drafts/specs").rglob("*.json")
                if (lambda d: d.get("division") == "기계설비" and d.get("section_no") == "9-3-2")
                (json.loads(p.read_text(encoding="utf8"))["draft"]))
    spec = json.loads(path.read_text(encoding="utf8"))["draft"]
    tables = {t["id"]: t for t in spec["tables"]}
    cells = []
    for diameter, rates in EXPECTED.items():
        table_id = "p759-t2" if int(diameter) <= 100 else "p760-t0"
        table = tables[table_id]
        for trade in TRADES:
            row = f"{diameter}mm | {trade}"
            assert row in table["values"], (table_id, row)
            for col, value in zip((f"콘크리트 두께 {thickness} {site}" for thickness in THICKNESS for site in SITES), rates):
                actual = table["values"][row][col]
                assert actual == value, (table_id, row, col, actual, value)
                citation = cite_table(table_id, row, col, value)
                expected_page = 759 if table_id == "p759-t2" else 760
                assert citation.get("value") == value and citation.get("pdf_page") == expected_page, citation
                cells.append({"table": table_id, "row": row, "column": col, "value": value})
    assert len(cells) == 80
    doc = pymupdf.open(PDF)
    for page_no, image in ((758, IMAGES[0]), (759, IMAGES[1])):
        doc[page_no].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(image)
    page759 = doc[758].get_text("text")
    page760 = doc[759].get_text("text")
    assert "9-3-2" in page759 and "25mm" in page759 and "100mm" in page759
    assert "150mm" in page760 and "400mm" in page760
    routes = []
    for diameter, thickness, site in itertools.product(EXPECTED, THICKNESS, SITES):
        inp = {"hole_diameter": f"{diameter}mm", "concrete_thickness": thickness,
               "structure_type": site, "quantity": "1"}
        result = per_unit(spec, inp)
        assert result.get("status") == "computed", (inp, result)
        expect = Fraction(EXPECTED[diameter][THICKNESS.index(thickness)*2 + SITES.index(site)])
        lines = {line["name"]: line for line in result["unit_lines"]}
        assert set(lines) == set(TRADES), (inp, lines.keys())
        assert all(Fraction(line["exact"]) == expect for line in lines.values()), (inp, expect, lines)
        expected_table = "p759-t2" if int(diameter) <= 100 else "p760-t0"
        assert all(line["citations"][0].get("pdf_page") == (759 if expected_table == "p759-t2" else 760) for line in lines.values())
        routes.append({**inp, "table": expected_table, "status": "computed", "labor_rate_each": str(expect)})
    blocked_by_field = {f["name"]: [] for f in spec["inputs"]}
    for rule in spec.get("blocked", []):
        for c in rule.get("blocked_if_all", ([rule["blocked_if"]] if rule.get("blocked_if") else [])):
            blocked_by_field[c["input"]].append(c)
    params = spec["quantity_model"]["params"]
    adjustments = params.get("surcharges", []) + params.get("note_adjustments", [])
    choices = [_values(f, blocked_by_field[f["name"]], adjustments) for f in spec["inputs"]]
    statuses = []
    for values in itertools.product(*choices):
        inputs = dict(zip((f["name"] for f in spec["inputs"]), values))
        statuses.append(CALCULATORS["per_unit"](spec, inputs).get("status"))
    assert len(statuses) == 40 and set(statuses) == {"computed"}, {"n": len(statuses), "statuses": sorted(set(statuses))}
    audit = {"id": spec["id"], "status": "source_cells_and_exact_table_axes_verified",
             "source": {"physical_pages": [759, 760], "printed_pages": [703, 704],
                        "images": [str(x.relative_to(ROOT)) for x in IMAGES], "pdf_sha256": sha(PDF),
                        "image_sha256": [sha(x) for x in IMAGES], "unique_source_cells_checked": len(cells), "cells": cells,
                        "layout": "p759 contains 25-100mm; continuation p760 contains 150-400mm. Within each diameter and trade row, each source value is repeated across all four thickness×site cells."},
             "runtime": {"exact_routes": len(routes), "routes": routes, "preflight_combinations": len(statuses), "preflight_statuses": {"computed": statuses.count("computed"), "blocked": statuses.count("blocked")}},
             "scope": "80 distinct source cells and 40 diameter/thickness/site combinations checked against the original PDF.",
             "spec_sha256": sha(path), "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"source_cells": len(cells), "routes": len(routes), "preflight": len(statuses), "audit": str(AUDIT.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
