"""Independent source and runtime audit for mechanical section 9-2-1."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from fractions import Fraction
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.source.citation import cite_table  # noqa: E402
from pipeline.validate_drafts import chunks_by_id_from_list, check_table_citation, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/9-2-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
IMAGE = ROOT / "evals/runtime_validation/source-p758-9-2-1-surface.png"
OUT = ROOT / "evals/runtime_validation/per-unit-9-2-1-source-audit-2026-10-19.json"
EXPECTED = {
    "Shot Blast": {"steel shot": "0.215", "ø1㎜ 기준": "0.415", "도장공": "0.0375", "보통인부": "0.0125"},
    "Sand Blast": {"규사함유량 80%": "0.0508", "모래분사공": "0.0329", "보통인부": "0.036"},
    "Power Tool": {"동력 Brush": "0.03", "도장공": "0.1", "보통인부": "-"},
    "Wire Brush": {"Gasolin": "0.05", "Wire Brush": "0.016", "도장공": "-", "보통인부": "0.05"},
}
UNITS = {"steel shot": "kg", "ø1㎜ 기준": "kg", "규사함유량 80%": "㎥", "동력 Brush": "개", "Gasolin": "ℓ", "Wire Brush": "개"}
LABOR = {"Shot Blast": {"도장공": "0.0375", "보통인부": "0.0125"},
         "Sand Blast": {"모래분사공": "0.0329", "보통인부": "0.036"},
         "Power Tool": {"도장공": "0.1"}, "Wire Brush": {"보통인부": "0.05"}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")
    package = json.loads(SPEC.read_text(encoding="utf-8")); spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p758-t1")
    assert table["unit"] == "인/㎡" and table["values"] == EXPECTED
    doc = pymupdf.open(PDF); source_text = doc[757].get_text("text")
    for token in ("9-2-1", "Shot", "Blast", "Sand", "Power", "Wire", "0.0375", "0.0125", "0.0508", "0.0329", "Gasolin", "50%", "100㎜"):
        assert token in source_text, token
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ci = chunks_by_id_from_list(chunks)
    cells = []
    for row, values in EXPECTED.items():
        assert table["values"][row] == values
        for col, value in values.items():
            citation = {"table_id": "p758-t1", "row": row, "column": col, "value": value}
            assert check_table_citation(ci, citation) is None, citation
            assert cite_table("p758-t1", row, col, value).get("value") == value
            cells.append(citation)
    assert len(cells) == 14
    cases = []
    for method, labor in LABOR.items():
        for small in (False, True):
            result = per_unit(spec, {"method": method, "quantity": "1", "is_small_section": small})
            assert result["status"] == "computed", (method, small, result)
            lines = result["unit_lines"]
            got_labor = {x["name"]: Fraction(x["exact"]) for x in lines if x["kind"] == "labor"}
            multiplier = Fraction(3, 2) if small else Fraction(1)
            assert got_labor == {name: Fraction(value) * multiplier for name, value in labor.items()}, (method, small, got_labor)
            materials = {x["name"]: Fraction(x["exact"]) for x in lines if x["kind"] == "material"}
            expected_materials = {name: Fraction(value) for name, value in EXPECTED[method].items() if name in UNITS}
            assert materials == expected_materials, (method, small, materials)
            excluded = {x["trade"] for x in result["provenance"]["excluded_resources"]}
            expected_excluded = {name for name, value in EXPECTED[method].items() if value == "-"}
            assert excluded == expected_excluded, (method, excluded, expected_excluded)
            cases.append({"method": method, "small_section": small, "status": "computed",
                          "labor": {k: str(v) for k, v in got_labor.items()},
                          "materials_per_sqm": {k: str(v) for k, v in materials.items()},
                          "source_dash_exclusions": sorted(excluded)})
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", ci, None)
    assert not validation.get("issues"), validation
    audit = {"id": spec["id"], "status": "source_cells_and_route_math_verified",
             "source": {"pdf_page": 758, "printed_page": 702, "image": str(IMAGE.relative_to(ROOT)),
                        "pdf_sha256": sha(PDF), "image_sha256": sha(IMAGE), "cells_checked": len(cells), "cells": cells},
             "runtime": {"routes_checked": len(cases), "cases": cases, "validation_issues": validation.get("issues", [])},
             "unresolved_source_rules": ["abrasive consumption adjustment depends on rust degree and shot cycle conditions (note ②)",
                                         "on-site sand/shot collection, loading, hauling and grading are separate (note ③)",
                                         "equipment/tool costs and consumables are separate (note ④)"],
             "rule_scope": {"verified": "all 15 numeric or dash cells, all four method routes, labor-only 50% small-section multiplier",
                            "all_rules_fully_verified": False},
             "spec_sha256": sha(SPEC), "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
             "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": audit["status"], "cells_checked": len(cells), "routes_checked": len(cases),
                      "validation_issues": validation.get("issues", []), "unresolved_rules": len(audit["unresolved_source_rules"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
