"""Verify 8-3-8 exact category-to-table routing against all source rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-8.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "고성능 착정기": ("p316-t0", [["7101-0450", "335.70", "6,300", "800", "0.9", "0.65", "0.1", "1,429", "1,032", "759", "3,220"]]),
    "하수관 천공기": ("p316-t1", [["7103-0010", "수동식", "6,300", "800", "0.9", "0.65", "0.1", "1,429", "1,032", "759", "3,220"]]),
    "상수도관 천공기": ("p316-t2", [["7104-0010", "수동식", "6,300", "800", "0.9", "0.65", "0.1", "1,429", "1,032", "759", "3,220"]]),
    "골재 살포기": ("p316-t3", [["7106-0035", "3.5", "8,000", "890", "0.9", "0.65", "0.1", "1,125", "813", "674", "2,612"]]),
    "진공흡입 준설차": ("p316-t4", [
        ["7110-0013", "13톤(3.00㎥적)", "8,400", "1,070", "0.9", "0.65", "0.1", "1,071", "774", "568", "2,413"],
        ["0025", "25톤(7.64㎥적)", "8,400", "1,070", "0.9", "0.65", "0.1", "1,071", "774", "568", "2,413"],
    ]),
}


def has_ordered_tokens(text: str, tokens: list[str]) -> bool:
    cursor = 0
    for token in tokens:
        position = text.find(token, cursor)
        if position < 0:
            return False
        cursor = position + len(token)
    return True


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    page = pymupdf.open(PDF)[315]
    source_text = page.get_text()
    checked_cells = 0
    lookup_paths = 0
    for category, (table_id, expected_rows) in EXPECTED.items():
        table = next(t for t in spec["tables"] if t["id"] == table_id)
        assert spec["inputs"][0]["source_table_map"][category] == table_id
        assert len(table["values"]) == len(expected_rows)
        for expected_row in expected_rows:
            code = expected_row[0]
            position = source_text.find(code)
            assert position >= 0, (category, code)
            block_end = source_text.find("\n[주]", position)
            if block_end < 0:
                block_end = min((x for x in [source_text.find("\n(", position + 1), len(source_text)] if x >= 0))
            block = source_text[position:block_end]
            assert has_ordered_tokens(block, expected_row[1:]), (category, code, block[:600])
            row_key = next((key for key in table["values"]
                            if key == code or key.endswith(code)), None)
            assert row_key is not None
            cells = table["values"][row_key]
            assert list(cells.values()) == expected_row, (category, row_key, cells, expected_row)
            checked_cells += len(expected_row)
        result = lookup(spec, {"machine_category": category})
        assert result["status"] == "computed" and result.get("table_reference") is True, (category, result)
        assert result["provenance"]["table"] == table_id
        assert result["value"] == table["values"]
        expected_citations = sum(len(row) for row in table["values"].values())
        assert len(result["provenance"]["citations"]) == expected_citations
        lookup_paths += 1

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_page": 260, "source_rows": sum(len(x[1]) for x in EXPECTED.values()),
                      "source_cells": checked_cells, "exact_category_table_routes": lookup_paths,
                      "multirow_vacuum_table_rows_returned": len(EXPECTED["진공흡입 준설차"][1]),
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
