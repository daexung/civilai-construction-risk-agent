"""Verify explicit machine-code suffix mapping for crane (tire) source rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/2104-0010.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
ROWS = {
    "80": ["80", "12.3", "57", "1"],
    "100": ["100", "15.9", "57", "1"],
    "130": ["130", "17.7", "63", "1"],
    "160": ["160", "19.6", "63", "1"],
    "200": ["200", "22", "63", "1"],
    "220": ["220", "22", "63", "1"],
    "250": ["250", "24", "63", "1"],
    "300ton": ["300ton", "24", "63", "1"],
}


def main() -> int:
    grid = pymupdf.open(PDF)[334].find_tables().tables[0].extract()
    codes = [x for x in grid[1][0].splitlines() if x.strip()]
    names = [x for x in grid[1][1].splitlines() if x.strip()]
    specs = [x for x in grid[1][2].splitlines() if x.strip()]
    fuels = [x for x in grid[1][3].splitlines() if x.strip()]
    misc = [x for x in grid[1][4].splitlines() if x.strip()]
    operators = [x for x in grid[1][5].splitlines() if x.strip()]
    assert codes[:8] == ["0080", "0100", "0130", "0160", "0200", "0220", "0250", "0300"]
    assert "크 레 인 ( 타 이 어 )" in names[0]
    source = {key: [specs[i], fuels[i], misc[i], operators[i]] for i, key in enumerate(ROWS)}
    assert source == ROWS, source

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p335-t0")
    checked = 0
    for choice, expected in ROWS.items():
        code = spec["inputs"][0]["machine_codes"][choice]
        assert code.startswith("2104-0010-")
        row_key = code.rsplit("-", 1)[1]
        expected_row = table["values"][row_key]
        assert [expected_row["규격"], expected_row["주연료\n(ℓ/hr)"],
                expected_row["잡재료\n(주연료의%)"], expected_row["조종원\n(인/일)"]] == expected
        result = lookup(spec, {"machine_spec": choice})
        assert result["status"] == "computed" and result.get("row_reference")
        assert result["value"] == expected_row and result["provenance"]["row"] == row_key
        assert len(result["provenance"]["citations"]) == len(expected_row)
        checked += len(expected)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "pdf_page": 335, "printed_page": 279,
                      "source_rows": len(ROWS), "source_cells": checked,
                      "exact_machine_code_routes": len(ROWS), "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
