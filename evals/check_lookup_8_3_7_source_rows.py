"""Independently compare the reconstructed 8-3-7 table rows with the PDF grid."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-7.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "6105-0190": ["190×2 (2㎾)", "4,000", "890", "0.9", "0.55", "0.1", "2,250", "1,375", "730", "4,355"],
    "0390": ["390×2 (5㎾)", "4,000", "890", "0.9", "0.55", "0.1", "2,250", "1,375", "730", "4,355"],
}


def normalized_cell(value: str) -> str:
    return " ".join(value.split())


def main() -> int:
    grid = pymupdf.open(PDF)[310].find_tables().tables[0].extract()
    codes = [x.strip() for x in grid[2][0].splitlines() if x.strip()]
    spec_lines = [x.strip() for x in grid[2][1].splitlines() if x.strip()]
    specs = [" ".join(spec_lines[i:i + 2]) for i in range(0, len(spec_lines), 2)]
    columns = [[x.strip() for x in grid[2][i].splitlines() if x.strip()] for i in range(2, 11)]
    source_rows = {}
    for row_index, code in enumerate(codes):
        source_rows[code] = [specs[row_index], *[column[row_index] for column in columns]]
    assert source_rows == EXPECTED, source_rows

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p311-t0")
    assert table["values"] == {k: dict(zip(["규격", "내용시간", "연간표준가동시간", "상각비율", "정비비율", "연간관리비율", "상각비계수", "정비비계수", "관리비계수", "계"], v)) for k, v in EXPECTED.items()}
    checked_lookup_cells = 0
    for code, expected in EXPECTED.items():
        result = lookup(spec, {"machine_code": code})
        key = code if code in table["values"] else f"6105-{code}"
        assert result["status"] == "computed" and result["value"] == table["values"][key], (code, result)
        assert result["provenance"]["table"] == "p311-t0"
        cited = [citation for line in result["unit_lines"] for citation in line["citations"]]
        assert len(cited) == len(expected) and all(c["internal_id"] == "p311-t0" for c in cited)
        checked_lookup_cells += len(expected)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "pdf_page": 311, "printed_page": 255, "source_rows": len(source_rows),
                      "source_cells": sum(map(len, source_rows.values())), "lookup_rows": len(source_rows),
                      "lookup_cells": checked_lookup_cells, "cell_citations": "pass", "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
