"""Source-backed check for the six floor-rate cell citations in 11-1-1.

This is a focused preflight check; it does not replay the 1,058-item inventory
or claim that every calculation rule in the section has been verified.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.validate_drafts import check_citations, load_chunks  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC = ROOT / "data/drafts/specs/건축/11-1-1.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
EXPECTED = {
    "지하층 및\n1∼3층": "0",
    "4∼6층": "5%",
    "7∼9층": "8%",
    "10∼12층": "12%",
    "13∼15층": "16%",
    "16∼18층": "20%",
}


def main() -> int:
    with pymupdf.open(PDF) as doc:
        tables = doc[690].find_tables().tables
        source = tables[1].extract()
    normalize = lambda value: "".join((value or "").split())
    actual = {normalize(label): normalize(rate) for label, rate in zip(source[0], source[1])}
    expected = {normalize(label): normalize(rate) for label, rate in EXPECTED.items()}
    assert actual == expected, {"source": actual, "expected": expected}

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    citations = [c for c in package["citations"] if c.get("table_id") == "p691-t1"]
    assert len(citations) == 6
    assert {normalize(c["column"]): normalize(c["value"]) for c in citations} == expected
    assert all("row" not in c for c in citations), "citation must not invent a literal row label"
    errors = check_citations(load_chunks(CHUNKS), citations)
    assert errors == [], errors
    print(json.dumps({"status": "pass", "section": "건축/11-1-1",
                      "source_page_printed": 635, "source_table_bbox": list(tables[1].bbox),
                      "independently_compared_cells": 12, "corrected_citations": 6,
                      "citation_errors": 0, "all_rule_verification": False},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
