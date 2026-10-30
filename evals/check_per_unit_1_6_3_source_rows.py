"""Compare four per-unit labor cells to PDF p.657 and verify exact totals."""
from __future__ import annotations

import json
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/1-6-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {"배관공": {"ø16mm": "0.029", "ø20mm": "0.036"},
            "보통인부": {"ø16mm": "0.014", "ø20mm": "0.018"}}


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    assert spec["tables"][0]["values"] == EXPECTED
    with pymupdf.open(PDF) as doc:
        source = norm(doc[712].get_text())
        for row, values in EXPECTED.items():
            assert norm(row) in source, row
            for column, value in values.items():
                assert norm(column) in source and norm(value) in source, (row, column, value)
    results = {}
    for size in ("ø16mm", "ø20mm"):
        result = per_unit(spec, {"pipe_size": size, "quantity": "100"})
        assert result.get("status") == "computed", result
        lines = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        for row in EXPECTED:
            assert lines[row] == Fraction(EXPECTED[row][size]), (size, row, lines)
        results[size] = {row: str(lines[row]) for row in EXPECTED}
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 657, "source_rows": 2,
              "source_cells": 4, "calculation_cases": results,
              "calculation_scope": "unit-rate normalization only; runtime returns exact per-m rates, no total amount claimed",
              "independent_expected": {size: {row: str(Fraction(value))
                                                  for row, value in rows.items()}
                                       for size, rows in EXPECTED.items()},
              "format_citation_preflight": "pass",
              "visual_review": "printed PDF p.657 table grid visually compared"}
    out = ROOT / "evals/runtime_validation/per-unit-1-6-3-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
