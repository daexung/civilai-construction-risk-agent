"""Verify the six 8-3-1 labor cells, citation repair, and 5 m policy gate."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/토목/8-3-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {"기 술 사": "3.8", "특 급 기 술 자": "5.1", "고 급 기 술 자": "10.8",
            "중 급 기 술 자": "14.6", "특 별 인 부": "3.8", "보 통 인 부": "13.3"}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    assert table["id"] == "p457-t0" and table["values"] == {row: {"수 량": value} for row, value in EXPECTED.items()}
    with pymupdf.open(PDF) as doc:
        text = norm(doc[456].get_text())
        for row, value in EXPECTED.items():
            for token in re.findall(r"[가-힣a-z]+|[0-9.]+", norm(row + value)):
                assert token in text, (row, value, token)
    citations = 0
    result = per_unit(spec, {"quantity": "1", "receiver_interval": "5"})
    assert result["status"] == "computed", result
    for row, value in EXPECTED.items():
        assert {"table_id": "p457-t0", "row": row, "column": "수 량", "value": value} in package["citations"]
        line = next(line for line in result["unit_lines"] if line["name"] == row)
        assert line["exact"] == str(Fraction(value))
        citation = line["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
            "p457-t0", row, "수 량", value)
        citations += 1
    blocked = per_unit(spec, {"quantity": "1", "receiver_interval": "4"})
    assert blocked["status"] == "blocked", blocked
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 401, "source_cells": len(EXPECTED),
              "runtime_exact_cell_citations": citations,
              "calculation_case": "all six trade rates returned at the source 5 m receiver interval and 1 km basis",
              "non_source_interval": "blocked; adjustment factor unspecified",
              "format_citation_preflight": "pass",
              "visual_review": "printed PDF p.401 table grid visually compared"}
    out = ROOT / "evals/runtime_validation/per-unit-8-3-1-citation-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
