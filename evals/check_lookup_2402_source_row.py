"""Verify restored 2402 source cells and the source-backed lookup result."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/2402-0001.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = ["2402-0001", "1,000", "5,000", "890", "0.9", "0.5", "0.1",
            "1,800", "1,000", "708", "3,508"]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    extracted = pymupdf.open(PDF)[294].find_tables().tables[3].extract()
    source_row = extracted[-1]
    assert source_row == EXPECTED, (source_row, EXPECTED)

    result = lookup(spec, {"spec": "1,000"})
    expected_cells = table["values"]["1,000"]
    assert result["status"] == "computed" and result["value"] == expected_cells, result
    assert len(result["provenance"]["citations"]) == len(EXPECTED) - 1
    assert all(c["internal_id"] == "p295-t3" and c["row"] == "1,000"
               for c in result["provenance"]["citations"])

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "table_id": "p295-t3", "printed_page": 239,
                      "independent_source_cells": 10, "lookup_result_cells": 10,
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
